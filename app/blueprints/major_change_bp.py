from app.utils.security import user_error_message
"""
Major Change Blueprint — 专业变更管理

Routes:
  GET  /             list_changes     — 所有变更记录（支持状态筛选）
  GET  /apply        apply_change     — 学生转专业申请表单
  POST /apply        apply_change     — 提交转专业申请
  GET  /approve      approve_queue    — 待审批变更记录
  POST /<id>/approve approve_change   — 审批通过
  POST /<id>/reject  reject_change    — 审批拒绝
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from datetime import date

from app.extensions import db
from app.models import MajorChange, Major, Class, Student
from app.utils.decorators import role_required

major_change_bp = Blueprint('major_change', __name__)


@major_change_bp.route('/')
@login_required
def list_changes():
    status_filter = request.args.get('status', '').strip()
    query = MajorChange.query.order_by(MajorChange.change_date.desc())
    if status_filter:
        query = query.filter(MajorChange.approval_status == status_filter)
    # 学生只看自己的变更记录，管理员看全部
    if current_user.role == 'student':
        query = query.filter(MajorChange.student_id == current_user.related_id)
    changes = query.all()
    statuses = ['待审批', '已通过', '已拒绝']
    return render_template('major_change/list.html',
                           changes=changes,
                           status_filter=status_filter,
                           statuses=statuses)


@major_change_bp.route('/apply', methods=['GET', 'POST'])
@login_required
@role_required('student')
def apply_change():
    student_id = str(current_user.related_id or '')
    if not student_id:
        abort(403)
    if request.method == 'POST' and request.form.get('student_id', student_id).strip() != student_id:
        abort(403)
    if request.method == 'POST':
        try:
            new_major_id = int(request.form['new_major_id'])
            reason = request.form.get('reason', '').strip() or None
            attachment = None

            student = Student.query.filter_by(student_id=student_id).with_for_update().first()
            if not student:
                flash('学生不存在', 'danger')
                return redirect(url_for('major_change.apply_change'))

            if student.status not in ('在读',):
                flash(f'学生当前状态为"{student.status}"，不允许申请转专业', 'warning')
                return redirect(url_for('major_change.apply_change'))

            if new_major_id == student.major_id:
                flash('目标专业与当前专业相同，无需变更', 'warning')
                return redirect(url_for('major_change.apply_change'))

            if MajorChange.query.filter_by(student_id=student_id, approval_status='待审批').first():
                flash('已有待审批申请，请勿重复提交', 'warning')
                return redirect(url_for('major_change.list_changes'))

            # 自动分配目标专业的同年级班级
            current_grade = student.class_.grade if student.class_ else None
            new_class = Class.query.filter_by(major_id=new_major_id, grade=current_grade).first()
            if not new_class:
                new_class = Class.query.filter_by(major_id=new_major_id).first()
            if not new_class:
                flash('目标专业暂无可用班级', 'danger')
                return redirect(url_for('major_change.apply_change'))

            change = MajorChange(
                student_id=student_id,
                old_major_id=student.major_id,
                new_major_id=new_major_id,
                change_date=date.today(),
                reason=reason,
                approval_status='待审批',
                attachment=attachment,
            )
            db.session.add(change)
            db.session.flush()
            uploaded = request.files.get('attachment')
            if uploaded and uploaded.filename:
                from app.services.file_service import save_uploaded_file
                record = save_uploaded_file(uploaded, 'major_change', change.change_id)
                change.attachment = url_for('file.download_file', file_id=record.file_id)
            db.session.commit()
            flash('转专业申请已提交，请等待审批', 'success')
            return redirect(url_for('major_change.list_changes'))
        except Exception as e:
            db.session.rollback()
            flash(f'申请提交失败: {user_error_message(e)}', 'danger')

    majors = Major.query.order_by(Major.major_name).all()
    classes = Class.query.order_by(Class.class_name).all()
    return render_template('major_change/apply.html',
                           majors=majors,
                           classes=classes)


@major_change_bp.route('/approve')
@login_required
@role_required('admin')
def approve_queue():
    pending = MajorChange.query \
        .filter(MajorChange.approval_status == '待审批') \
        .order_by(MajorChange.change_date.asc()).all()
    return render_template('major_change/approve.html', pending=pending)


@major_change_bp.route('/<int:change_id>/approve', methods=['POST'])
@login_required
@role_required('admin')
def approve_change(change_id):
    change = MajorChange.query.filter_by(change_id=change_id).with_for_update().first_or_404()
    try:
        if change.approval_status != '待审批':
            flash('该转专业申请已处理，请勿重复审批', 'warning')
            return redirect(url_for('major_change.approve_queue'))

        student = Student.query.filter_by(student_id=change.student_id).with_for_update().first()
        if not student:
            flash('关联学生不存在', 'danger')
            return redirect(url_for('major_change.approve_queue'))

        if student.status != '在读' or student.major_id != change.old_major_id:
            flash('学生状态或专业已变化，请重新提交申请', 'warning')
            return redirect(url_for('major_change.approve_queue'))

        # 自动分配新专业的同年级班级
        current_grade = student.class_.grade if student.class_ else None
        new_class = Class.query.filter_by(major_id=change.new_major_id, grade=current_grade).first()
        if not new_class:
            new_class = Class.query.filter_by(major_id=change.new_major_id).first()
        if not new_class:
            flash('目标专业暂无可用班级，无法审批', 'danger')
            return redirect(url_for('major_change.approve_queue'))

        student.major_id = change.new_major_id
        student.class_id = new_class.class_id
        change.approval_status = '已通过'
        change.approver_id = current_user.user_id
        change.approval_date = db.func.now()
        db.session.commit()
        flash('专业变更成功', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'审批失败: {user_error_message(e)}', 'danger')
    return redirect(url_for('major_change.approve_queue'))


@major_change_bp.route('/<int:change_id>/reject', methods=['POST'])
@login_required
@role_required('admin')
def reject_change(change_id):
    change = MajorChange.query.filter_by(change_id=change_id).with_for_update().first_or_404()
    try:
        if change.approval_status != '待审批':
            flash('该转专业申请已处理，请勿重复审批', 'warning')
            return redirect(url_for('major_change.approve_queue'))
        change.approval_status = '已拒绝'
        change.approver_id = current_user.user_id
        change.approval_date = db.func.now()
        db.session.commit()
        flash('已拒绝该转专业申请', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'操作失败: {user_error_message(e)}', 'danger')
    return redirect(url_for('major_change.approve_queue'))
