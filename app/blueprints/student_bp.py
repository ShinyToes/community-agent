from app.utils.security import user_error_message
import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Student, Major, Class, Enrollment, File, User
from app.utils.decorators import admin_required, role_required
from app.utils.helpers import get_status_badge
from app.services.file_service import save_uploaded_file, delete_file_record, get_files_for_record
from app.utils.security import require_student_access
from app.utils.validation import validate_student

student_bp = Blueprint('student', __name__)

ALLOWED_ROLES = ('admin',)


@student_bp.route('/')
@login_required
def list_students():
    q = request.args.get('q', '').strip()
    major_id = request.args.get('major_id', '').strip()
    class_id = request.args.get('class_id', '').strip()
    status = request.args.get('status', '').strip()
    enrollment_year = request.args.get('enrollment_year', '').strip()

    query = Student.query
    if current_user.role == 'student':
        query = query.filter(Student.student_id == current_user.related_id)

    if q:
        query = query.filter(
            db.or_(
                Student.student_id.like(f'%{q}%'),
                Student.name.like(f'%{q}%'),
                Student.phone.like(f'%{q}%'),
            )
        )
    if major_id:
        query = query.filter(Student.major_id == int(major_id))
    if class_id:
        query = query.filter(Student.class_id == int(class_id))
    if status:
        query = query.filter(Student.status == status)
    if enrollment_year:
        query = query.filter(Student.enrollment_year == int(enrollment_year))

    students = query.order_by(Student.student_id).all()
    majors = Major.query.order_by(Major.major_name).all()
    classes = Class.query.order_by(Class.class_name).all()
    # Get distinct enrollment years for filter
    from sqlalchemy import distinct
    years = [r[0] for r in db.session.query(distinct(Student.enrollment_year)).order_by(Student.enrollment_year.desc()).all()]

    return render_template(
        'student/list.html',
        students=students,
        majors=majors,
        classes=classes,
        years=years,
        search_params={'q': q, 'major_id': major_id, 'class_id': class_id,
                       'status': status, 'enrollment_year': enrollment_year},
        get_status_badge=get_status_badge,
    )


@student_bp.route('/create', methods=['GET', 'POST'])
@login_required
@role_required(*ALLOWED_ROLES)
def create_student():
    if request.method == 'POST':
        try:
            student = Student(
                student_id=request.form['student_id'].strip(),
                name=request.form['name'].strip(),
                gender=request.form['gender'].strip(),
                birth_date=request.form.get('birth_date') or None,
                id_card=request.form.get('id_card', '').strip() or None,
                ethnicity=request.form.get('ethnicity', '').strip() or None,
                political_status=request.form.get('political_status', '').strip() or None,
                native_place=request.form.get('native_place', '').strip() or None,
                home_address=request.form.get('home_address', '').strip() or None,
                phone=request.form.get('phone', '').strip() or None,
                email=request.form.get('email', '').strip() or None,
                enrollment_year=int(request.form['enrollment_year']) if request.form.get('enrollment_year') else 2026,
                education_length=int(request.form.get('education_length', 4)),
                education_level=request.form['education_level'].strip(),
                status=request.form.get('status', '在读').strip(),
                major_id=int(request.form['major_id']),
                class_id=int(request.form['class_id']),
            )

            validate_student(student)
            db.session.add(student)
            db.session.flush()  # Get student.student_id for file reference without committing

            # Handle photo upload
            photo_file = request.files.get('photo')
            if photo_file and photo_file.filename:
                file_record = save_uploaded_file(photo_file, 'student', student.student_id)
                if file_record:
                    if file_record.file_type != 'image':
                        raise ValueError('照片必须是 JPG、PNG、GIF 或 WEBP 图片')
                    student.photo = file_record.file_path

            db.session.commit()
            flash('学生信息添加成功', 'success')
            return redirect(url_for('student.list_students'))
        except Exception as e:
            db.session.rollback()
            flash(f'添加失败: {user_error_message(e)}', 'danger')

    majors = Major.query.order_by(Major.major_name).all()
    classes = Class.query.order_by(Class.class_name).all()
    return render_template('student/form.html', student=None, majors=majors, classes=classes)


@student_bp.route('/<student_id>')
@login_required
def detail_student(student_id):
    require_student_access(student_id)
    student = Student.query.get_or_404(student_id)
    files = get_files_for_record('student', student_id)
    return render_template(
        'student/detail.html',
        student=student,
        files=files,
        get_status_badge=get_status_badge,
    )


@student_bp.route('/<student_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(*ALLOWED_ROLES)
def edit_student(student_id):
    student = Student.query.get_or_404(student_id)
    if request.method == 'POST':
        try:
            student.name = request.form['name'].strip()
            student.gender = request.form['gender'].strip()
            student.birth_date = request.form.get('birth_date') or None
            student.id_card = request.form.get('id_card', '').strip() or None
            student.ethnicity = request.form.get('ethnicity', '').strip() or None
            student.political_status = request.form.get('political_status', '').strip() or None
            student.native_place = request.form.get('native_place', '').strip() or None
            student.home_address = request.form.get('home_address', '').strip() or None
            student.phone = request.form.get('phone', '').strip() or None
            student.email = request.form.get('email', '').strip() or None
            student.enrollment_year = int(request.form['enrollment_year']) if request.form.get('enrollment_year') else student.enrollment_year
            student.education_length = int(request.form.get('education_length', student.education_length))
            student.education_level = request.form['education_level'].strip()
            student.status = request.form.get('status', '在读').strip()
            student.major_id = int(request.form['major_id'])
            student.class_id = int(request.form['class_id'])
            validate_student(student)

            # Handle photo upload
            photo_file = request.files.get('photo')
            if photo_file and photo_file.filename:
                # Delete old photo file record if exists
                if student.photo:
                    old_files = File.query.filter_by(
                        related_table='student', related_id=str(student.student_id),
                        file_type='image'
                    ).all()
                    for f in old_files:
                        delete_file_record(f.file_id)
                file_record = save_uploaded_file(photo_file, 'student', student.student_id)
                if file_record:
                    if file_record.file_type != 'image':
                        raise ValueError('照片必须是 JPG、PNG、GIF 或 WEBP 图片')
                    student.photo = file_record.file_path

            db.session.commit()
            flash('学生信息修改成功', 'success')
            return redirect(url_for('student.detail_student', student_id=student.student_id))
        except Exception as e:
            db.session.rollback()
            flash(f'修改失败: {user_error_message(e)}', 'danger')

    majors = Major.query.order_by(Major.major_name).all()
    classes = Class.query.order_by(Class.class_name).all()
    return render_template('student/form.html', student=student, majors=majors, classes=classes)


@student_bp.route('/<student_id>/delete', methods=['POST'])
@login_required
@role_required(*ALLOWED_ROLES)
def delete_student(student_id):
    student = Student.query.get_or_404(student_id)
    # Preserve academic history instead of cascading away completed grades.
    active_enrollments = Enrollment.query.filter(
        Enrollment.student_id == student_id
    ).count()
    if active_enrollments > 0:
        flash(f'该学生有 {active_enrollments} 条选课历史，不能删除；请通过学籍状态管理。', 'danger')
        return redirect(url_for('student.detail_student', student_id=student_id))

    try:
        # Clean up associated files
        related_files = get_files_for_record('student', student_id)
        for f in related_files:
            delete_file_record(f.file_id)

        User.query.filter_by(role='student', related_id=student_id).update({'is_active': False})
        db.session.delete(student)
        db.session.commit()
        flash('学生信息已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {user_error_message(e)}', 'danger')
    return redirect(url_for('student.list_students'))


@student_bp.route('/api/students/<student_id>')
@login_required
def api_get_student(student_id):
    """JSON API: 根据学号查询学生基本信息"""
    require_student_access(student_id)
    student = Student.query.get(student_id)
    if not student:
        return jsonify({'error': '学生不存在'}), 404
    return jsonify({
        'student_id': student.student_id,
        'name': student.name,
        'major_id': student.major_id,
        'major_name': student.major.major_name if student.major else '',
        'class_id': student.class_id,
        'class_name': student.class_.class_name if student.class_ else '',
    })
