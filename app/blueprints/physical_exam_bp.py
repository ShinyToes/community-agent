from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.models import PhysicalExam, Student, Class
from app.extensions import db
from app.utils.decorators import role_required
from datetime import datetime

physical_exam_bp = Blueprint('physical_exam', __name__)


@physical_exam_bp.route('/')
@login_required
def list_exams():
    student_id = request.args.get('student_id', '').strip()
    class_id = request.args.get('class_id', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    query = PhysicalExam.query.join(Student, PhysicalExam.student_id == Student.student_id)

    if current_user.role != 'admin':
        query = query.filter(PhysicalExam.student_id == current_user.related_id)

    if student_id:
        query = query.filter(
            (PhysicalExam.student_id.like(f'%{student_id}%')) |
            (Student.name.like(f'%{student_id}%'))
        )
    if class_id:
        query = query.filter(Student.class_id == class_id)
    if date_from:
        query = query.filter(PhysicalExam.exam_date >= date_from)
    if date_to:
        query = query.filter(PhysicalExam.exam_date <= date_to)

    exams = query.order_by(PhysicalExam.exam_date.desc()).all()
    classes = Class.query.order_by(Class.class_name).all()

    return render_template('physical_exam/list.html', exams=exams, classes=classes)


@physical_exam_bp.route('/create', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def create_exam():
    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        exam_date = request.form.get('exam_date', '').strip()
        height = request.form.get('height', '').strip()
        weight = request.form.get('weight', '').strip()
        vision_left = request.form.get('vision_left', '').strip()
        vision_right = request.form.get('vision_right', '').strip()
        blood_type = request.form.get('blood_type', '').strip()
        health_status = request.form.get('health_status', '').strip()
        hospital = request.form.get('hospital', '').strip()

        if not all([student_id, exam_date]):
            flash('请填写所有必填字段。', 'danger')
            return render_template('physical_exam/form.html', exam=None)

        exam = PhysicalExam(
            student_id=student_id,
            exam_date=datetime.strptime(exam_date, '%Y-%m-%d').date(),
            height=float(height) if height else None,
            weight=float(weight) if weight else None,
            vision_left=float(vision_left) if vision_left else None,
            vision_right=float(vision_right) if vision_right else None,
            blood_type=blood_type if blood_type else None,
            health_status=health_status if health_status else None,
            hospital=hospital if hospital else None,
            report_file=request.form.get('report_file', '').strip() or None
        )

        db.session.add(exam)
        db.session.commit()
        flash('体检记录创建成功！', 'success')
        return redirect(url_for('physical_exam.list_exams'))

    return render_template('physical_exam/form.html', exam=None)


@physical_exam_bp.route('/<int:exam_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_exam(exam_id):
    exam = PhysicalExam.query.get_or_404(exam_id)

    if request.method == 'POST':
        exam.student_id = request.form.get('student_id', '').strip()
        exam_date = request.form.get('exam_date', '').strip()
        exam.exam_date = datetime.strptime(exam_date, '%Y-%m-%d').date() if exam_date else exam.exam_date

        height = request.form.get('height', '').strip()
        weight = request.form.get('weight', '').strip()
        vision_left = request.form.get('vision_left', '').strip()
        vision_right = request.form.get('vision_right', '').strip()

        exam.height = float(height) if height else None
        exam.weight = float(weight) if weight else None
        exam.vision_left = float(vision_left) if vision_left else None
        exam.vision_right = float(vision_right) if vision_right else None

        blood_type = request.form.get('blood_type', '').strip()
        health_status = request.form.get('health_status', '').strip()
        hospital = request.form.get('hospital', '').strip()

        exam.blood_type = blood_type if blood_type else None
        exam.health_status = health_status if health_status else None
        exam.hospital = hospital if hospital else None

        report_file = request.form.get('report_file', '').strip()
        if report_file:
            exam.report_file = report_file

        db.session.commit()
        flash('体检记录更新成功！', 'success')
        return redirect(url_for('physical_exam.list_exams'))

    return render_template('physical_exam/form.html', exam=exam)


@physical_exam_bp.route('/<int:exam_id>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_exam(exam_id):
    exam = PhysicalExam.query.get_or_404(exam_id)
    db.session.delete(exam)
    db.session.commit()
    flash('体检记录已删除。', 'success')
    return redirect(url_for('physical_exam.list_exams'))


@physical_exam_bp.route('/stats')
@login_required
@role_required('admin')
def stats():
    return render_template('physical_exam/stats.html')


@physical_exam_bp.route('/api/stats')
@login_required
@role_required('admin')
def api_stats():
    exams = PhysicalExam.query.all()

    # Height distribution
    height_bins = ['<150', '150-159', '160-169', '170-179', '180-189', '>=190']
    height_values = [150, 160, 170, 180, 190]
    height_counts = [0] * 6
    for exam in exams:
        if exam.height is None:
            continue
        h = exam.height
        if h < 150:
            height_counts[0] += 1
        elif h < 160:
            height_counts[1] += 1
        elif h < 170:
            height_counts[2] += 1
        elif h < 180:
            height_counts[3] += 1
        elif h < 190:
            height_counts[4] += 1
        else:
            height_counts[5] += 1

    # Weight distribution
    weight_bins = ['<50', '50-59', '60-69', '70-79', '80-89', '>=90']
    weight_counts = [0] * 6
    for exam in exams:
        if exam.weight is None:
            continue
        w = exam.weight
        if w < 50:
            weight_counts[0] += 1
        elif w < 60:
            weight_counts[1] += 1
        elif w < 70:
            weight_counts[2] += 1
        elif w < 80:
            weight_counts[3] += 1
        elif w < 90:
            weight_counts[4] += 1
        else:
            weight_counts[5] += 1

    # Vision distribution (left vs right grouped)
    vision_bins = ['<4.0', '4.0-4.5', '4.6-4.9', '5.0-5.2', '>5.2']
    vision_left_counts = [0] * 5
    vision_right_counts = [0] * 5
    for exam in exams:
        vl = exam.vision_left
        vr = exam.vision_right
        for i, val in enumerate([vl, vr]):
            if val is None:
                continue
            idx = 0
            if val < 4.0:
                idx = 0
            elif val <= 4.5:
                idx = 1
            elif val <= 4.9:
                idx = 2
            elif val <= 5.2:
                idx = 3
            else:
                idx = 4
            if i == 0:
                vision_left_counts[idx] += 1
            else:
                vision_right_counts[idx] += 1

    # Blood type distribution
    blood_types = ['A', 'B', 'AB', 'O']
    blood_counts = {bt: 0 for bt in blood_types}
    for exam in exams:
        if exam.blood_type and exam.blood_type.upper() in blood_counts:
            blood_counts[exam.blood_type.upper()] += 1

    # Health status distribution
    health_statuses = ['健康', '良好', '一般', '较差']
    health_counts = [0] * 4
    for exam in exams:
        if exam.health_status:
            try:
                idx = health_statuses.index(exam.health_status)
                health_counts[idx] += 1
            except ValueError:
                pass

    return jsonify({
        'height': {
            'labels': height_bins,
            'values': height_counts
        },
        'weight': {
            'labels': weight_bins,
            'values': weight_counts
        },
        'vision': {
            'labels': vision_bins,
            'left_values': vision_left_counts,
            'right_values': vision_right_counts
        },
        'blood_type': {
            'labels': blood_types,
            'values': [blood_counts[bt] for bt in blood_types]
        },
        'health_status': {
            'labels': health_statuses,
            'values': health_counts
        }
    })
