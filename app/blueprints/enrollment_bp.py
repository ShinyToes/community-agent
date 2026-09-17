from app.utils.security import user_error_message
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models import Enrollment, CourseOffering, Course, Student, Teacher
from app.services.enrollment_service import enroll_student, check_course_conflict
from app.utils.decorators import role_required

enrollment_bp = Blueprint('enrollment', __name__)


@enrollment_bp.route('/')
@login_required
def my_enrollments():
    if current_user.role == 'student':
        enrollments = (
            Enrollment.query
            .options(
                joinedload(Enrollment.offering).joinedload(CourseOffering.course),
                joinedload(Enrollment.offering).joinedload(CourseOffering.teacher)
            )
            .filter_by(student_id=str(current_user.related_id))
            .filter(Enrollment.status != '退课')
            .order_by(Enrollment.enrollment_id.desc())
            .all()
        )
        return render_template('enrollment/my_courses.html', enrollments=enrollments, student_search=False)
    else:
        student_id = request.args.get('student_id', '').strip()
        enrollments = []
        searched_name = ''
        if student_id:
            student = Student.query.get(student_id)
            if student:
                searched_name = student.name
                enrollments = (
                    Enrollment.query
                    .filter_by(student_id=student_id)
                    .order_by(Enrollment.enrollment_id.desc())
                    .all()
                )
            else:
                flash('未找到该学生', 'warning')
        return render_template('enrollment/my_courses.html', enrollments=enrollments,
                               student_search=True, searched_id=student_id,
                               searched_name=searched_name)


@enrollment_bp.route('/available')
@login_required
@role_required('student')
def available_courses():
    semester_filter = request.args.get('semester', '').strip()
    student_id = str(current_user.related_id)

    # 获取学生已选且未退课/未通过的课程ID
    # "在修"和"已通过"的课程不可重复选；"未通过"和"退课"的课程允许重新选课
    enrolled_course_ids = [co.course_id for co in
        CourseOffering.query.join(Enrollment).filter(
            Enrollment.student_id == student_id,
            Enrollment.status.in_(['在修', '已通过'])
        ).all()]

    query = CourseOffering.query.options(
        joinedload(CourseOffering.course),
        joinedload(CourseOffering.teacher)
    ).filter(CourseOffering.academic_year == '2025-2026')
    if semester_filter:
        query = query.filter(CourseOffering.semester == semester_filter)
    if enrolled_course_ids:
        query = query.filter(~CourseOffering.course_id.in_(enrolled_course_ids))

    offerings = query.order_by(CourseOffering.offering_id).all()
    return render_template('enrollment/available.html', offerings=offerings,
                           semester_filter=semester_filter)


@enrollment_bp.route('/check-conflict/<int:offering_id>')
@login_required
@role_required('student')
def api_check_conflict(offering_id):
    """JSON API: 检查选课时间冲突"""
    student_id = str(current_user.related_id)
    try:
        has_conflict = check_course_conflict(student_id, offering_id)
        return jsonify({'has_conflict': has_conflict})
    except Exception as e:
        return jsonify({'has_conflict': None, 'error': '冲突检查暂不可用'}), 503


@enrollment_bp.route('/enroll', methods=['POST'])
@login_required
@role_required('student')
def enroll():
    offering_id = request.form.get('offering_id', type=int)
    if not offering_id or offering_id <= 0:
        return jsonify(error='开课编号无效'), 400
    student_id = str(current_user.related_id)
    try:
        success, message = enroll_student(student_id, offering_id)
    except Exception:
        db.session.rollback()
        raise
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('enrollment.available_courses'))


@enrollment_bp.route('/<int:enrollment_id>/drop', methods=['POST'])
@login_required
@role_required('student')
def drop_enrollment(enrollment_id):
    # Same lock order as enrollment: student, offering, enrollment.
    Student.query.filter_by(student_id=str(current_user.related_id)).with_for_update().first_or_404()
    enrollment = Enrollment.query.get_or_404(enrollment_id)

    if str(enrollment.student_id) != str(current_user.related_id):
        flash('无权操作此选课记录', 'danger')
        return redirect(url_for('enrollment.my_enrollments'))

    offering = CourseOffering.query.filter_by(offering_id=enrollment.offering_id).with_for_update().populate_existing().first_or_404()
    enrollment = Enrollment.query.filter_by(enrollment_id=enrollment_id).with_for_update().populate_existing().first_or_404()
    if enrollment.status != '在修':
        flash('该课程当前状态不允许退课', 'warning')
        return redirect(url_for('enrollment.my_enrollments'))

    try:
        enrollment.status = '退课'
        if offering.cur_students > 0:
            offering.cur_students -= 1
        db.session.commit()
        flash('退课成功', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'退课失败: {user_error_message(e)}', 'danger')

    return redirect(url_for('enrollment.my_enrollments'))
