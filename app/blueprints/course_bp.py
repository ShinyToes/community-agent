from app.utils.security import user_error_message
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.services.grade_validation import validate_weights
from app.models import Course, CourseOffering, Teacher, College
from app.utils.decorators import admin_required, role_required

course_bp = Blueprint('course', __name__)


# ============================================================
# Course CRUD
# ============================================================
@course_bp.route('/')
@login_required
def list_courses():
    course_type_filter = request.args.get('course_type', '').strip()
    department_filter = request.args.get('department', '').strip()

    query = Course.query
    if course_type_filter:
        query = query.filter_by(course_type=course_type_filter)
    if department_filter:
        query = query.filter(Course.department.like(f'%{department_filter}%'))

    courses = query.order_by(Course.course_id).all()
    return render_template('course/list.html', courses=courses,
                           course_type_filter=course_type_filter,
                           department_filter=department_filter)


@course_bp.route('/create', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def create_course():
    teachers = Teacher.query.order_by(Teacher.name).all()
    colleges = College.query.order_by(College.college_name).all()
    if request.method == 'POST':
        try:
            course = Course(
                course_code=request.form['course_code'].strip(),
                course_name=request.form['course_name'].strip(),
                credits=float(request.form['credits']),
                hours=int(request.form['hours']),
                course_type=request.form['course_type'].strip(),
                department=request.form.get('department', '').strip() or None,
                description=request.form.get('description', '').strip() or None,
                syllabus=request.form.get('syllabus', '').strip() or None,
                college_id=int(request.form['college_id']) if request.form.get('college_id') else None,
            )
            db.session.add(course)
            db.session.commit()
            flash('课程添加成功', 'success')
            return redirect(url_for('course.list_courses'))
        except Exception as e:
            db.session.rollback()
            flash(f'添加失败: {user_error_message(e)}', 'danger')
    return render_template('course/form.html', course=None, teachers=teachers, colleges=colleges)


@course_bp.route('/<int:course_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_course(course_id):
    course = Course.query.get_or_404(course_id)
    teachers = Teacher.query.order_by(Teacher.name).all()
    colleges = College.query.order_by(College.college_name).all()
    if request.method == 'POST':
        try:
            course.course_code = request.form['course_code'].strip()
            course.course_name = request.form['course_name'].strip()
            course.credits = float(request.form['credits'])
            course.hours = int(request.form['hours'])
            course.course_type = request.form['course_type'].strip()
            course.department = request.form.get('department', '').strip() or None
            course.description = request.form.get('description', '').strip() or None
            course.syllabus = request.form.get('syllabus', '').strip() or None
            course.college_id = int(request.form['college_id']) if request.form.get('college_id') else None
            db.session.commit()
            flash('课程修改成功', 'success')
            return redirect(url_for('course.list_courses'))
        except Exception as e:
            db.session.rollback()
            flash(f'修改失败: {user_error_message(e)}', 'danger')
    return render_template('course/form.html', course=course, teachers=teachers, colleges=colleges)


@course_bp.route('/<int:course_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_course(course_id):
    course = Course.query.get_or_404(course_id)
    try:
        db.session.delete(course)
        db.session.commit()
        flash('课程已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败(可能存在关联数据): {user_error_message(e)}', 'danger')
    return redirect(url_for('course.list_courses'))


# ============================================================
# Course Offering CRUD
# ============================================================
@course_bp.route('/offerings')
@login_required
def list_offerings():
    academic_year_filter = request.args.get('academic_year', '').strip()
    semester_filter = request.args.get('semester', '').strip()

    query = CourseOffering.query.options(
        joinedload(CourseOffering.course),
        joinedload(CourseOffering.teacher)
    )
    if academic_year_filter:
        query = query.filter_by(academic_year=academic_year_filter)
    if semester_filter:
        query = query.filter_by(semester=semester_filter)

    offerings = query.order_by(CourseOffering.offering_id).all()
    return render_template('course/offering.html', offerings=offerings,
                           academic_year_filter=academic_year_filter,
                           semester_filter=semester_filter)


@course_bp.route('/offerings/create', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def create_offering():
    courses = Course.query.order_by(Course.course_name).all()
    # 按姓名和院系排序，并在模板中显示院系以区分同名教师
    teachers = Teacher.query.order_by(Teacher.name, Teacher.department).all()
    if request.method == 'POST':
        try:
            offering = CourseOffering(
                course_id=int(request.form['course_id']),
                teacher_id=int(request.form['teacher_id']),
                academic_year=request.form['academic_year'].strip(),
                semester=request.form['semester'].strip(),
                classroom=request.form.get('classroom', '').strip() or None,
                schedule=request.form.get('schedule', '').strip() or None,
                max_students=int(request.form['max_students']),
                daily_weight=float(request.form.get('daily_weight', 0.30)),
                midterm_weight=float(request.form.get('midterm_weight', 0.30)),
                final_weight=float(request.form.get('final_weight', 0.40)),
            )
            validate_weights((offering.daily_weight, offering.midterm_weight, offering.final_weight))
            if offering.max_students <= 0:
                raise ValueError('课程容量必须为正整数')
            db.session.add(offering)
            db.session.commit()
            flash('开课信息添加成功', 'success')
            return redirect(url_for('course.list_offerings'))
        except Exception as e:
            db.session.rollback()
            flash(f'添加失败: {user_error_message(e)}', 'danger')
    return render_template('course/offering_form.html', offering=None, courses=courses, teachers=teachers)


@course_bp.route('/offerings/<int:offering_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_offering(offering_id):
    offering = CourseOffering.query.get_or_404(offering_id)
    courses = Course.query.order_by(Course.course_name).all()
    teachers = Teacher.query.order_by(Teacher.name, Teacher.department).all()
    if request.method == 'POST':
        try:
            offering.course_id = int(request.form['course_id'])
            offering.teacher_id = int(request.form['teacher_id'])
            offering.academic_year = request.form['academic_year'].strip()
            offering.semester = request.form['semester'].strip()
            offering.classroom = request.form.get('classroom', '').strip() or None
            offering.schedule = request.form.get('schedule', '').strip() or None
            offering.max_students = int(request.form['max_students'])
            offering.daily_weight = float(request.form.get('daily_weight', 0.30))
            offering.midterm_weight = float(request.form.get('midterm_weight', 0.30))
            offering.final_weight = float(request.form.get('final_weight', 0.40))
            validate_weights((offering.daily_weight, offering.midterm_weight, offering.final_weight))
            if offering.max_students <= 0 or offering.max_students < offering.cur_students:
                raise ValueError('课程容量必须为正整数且不能低于已选人数')
            db.session.commit()
            flash('开课信息修改成功', 'success')
            return redirect(url_for('course.list_offerings'))
        except Exception as e:
            db.session.rollback()
            flash(f'修改失败: {user_error_message(e)}', 'danger')
    return render_template('course/offering_form.html', offering=offering, courses=courses, teachers=teachers)


@course_bp.route('/offerings/<int:offering_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_offering(offering_id):
    offering = CourseOffering.query.get_or_404(offering_id)
    try:
        db.session.delete(offering)
        db.session.commit()
        flash('开课信息已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败(可能存在关联数据): {user_error_message(e)}', 'danger')
    return redirect(url_for('course.list_offerings'))
