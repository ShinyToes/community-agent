from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Grade, Enrollment, CourseOffering, Course, Student, Class
from app.services.grade_service import score_to_gpa, get_student_gpa, get_class_ranking, get_completed_credits
from app.utils.audit import set_audit_user
from app.utils.decorators import role_required
from app.utils.helpers import get_status_badge
from decimal import Decimal
from app.services.grade_validation import parse_score, weighted_total
from app.services.grade_writer import write_grade
from app.services.imports.profiles import snapshot
from app.agent_models import ChangeEvent

grade_bp = Blueprint('grade', __name__)


def auto_calculate(grade, offering=None):
    defaults = (Decimal('0.30'), Decimal('0.30'), Decimal('0.40'))
    weights = tuple(getattr(offering, name, None) for name in
                    ('daily_weight', 'midterm_weight', 'final_weight')) if offering else defaults
    weights = tuple(default if w is None else w for w, default in zip(weights, defaults))
    grade.total_score = weighted_total(
        (grade.daily_score, grade.midterm_score, grade.final_score), weights)
    grade.gpa = score_to_gpa(grade.total_score) if grade.total_score is not None else None


@grade_bp.route('/', methods=['GET'])
@login_required
@role_required('admin')
def list_offerings_for_grade():
    """List course offerings for grade entry."""
    academic_year = request.args.get('academic_year', '')
    semester = request.args.get('semester', '')

    query = CourseOffering.query.join(Course)

    if academic_year:
        query = query.filter(CourseOffering.academic_year == academic_year)
    if semester:
        query = query.filter(CourseOffering.semester == semester)

    # If teacher, only show their offerings
    if current_user.role == 'teacher':
        query = query.filter(CourseOffering.teacher_id == current_user.related_id)

    offerings = query.order_by(CourseOffering.academic_year.desc(),
                               CourseOffering.semester).distinct().all()

    # Get distinct academic years and semesters for filter dropdowns
    academic_years = db.session.query(CourseOffering.academic_year).distinct().order_by(
        CourseOffering.academic_year.desc()).all()
    semesters = db.session.query(CourseOffering.semester).distinct().order_by(
        CourseOffering.semester).all()

    return render_template('grade/offerings_list.html',
                           offerings=offerings,
                           academic_years=[ay[0] for ay in academic_years],
                           semesters=[s[0] for s in semesters],
                           current_academic_year=academic_year,
                           current_semester=semester)


@grade_bp.route('/offering/<int:offering_id>', methods=['GET'])
@login_required
@role_required('admin')
def entry_form(offering_id):
    """Grade entry sheet showing all students enrolled in this offering."""
    offering = (CourseOffering.query.filter_by(offering_id=offering_id).with_for_update().populate_existing().first_or_404()
                if request.method == 'POST' else CourseOffering.query.get_or_404(offering_id))

    # Authorization: teacher can only access their own offerings
    if current_user.role == 'teacher' and offering.teacher_id != current_user.related_id:
        flash('无权访问此开课的成绩录入', 'danger')
        return redirect(url_for('grade.list_offerings_for_grade'))

    # Get all active enrollments (not withdrawn)
    enrollments = Enrollment.query.filter_by(offering_id=offering_id)\
        .filter(Enrollment.status != '退课')\
        .order_by(Enrollment.student_id).all()

    return render_template('grade/entry.html',
                           offering=offering,
                           enrollments=enrollments)


@grade_bp.route('/offering/<int:offering_id>', methods=['POST'])
@login_required
@role_required('admin')
def submit_grades(offering_id):
    """Batch save grades for an offering."""
    offering = (CourseOffering.query.filter_by(offering_id=offering_id).with_for_update().populate_existing().first_or_404()
                if request.method == 'POST' else CourseOffering.query.get_or_404(offering_id))

    if current_user.role == 'teacher' and offering.teacher_id != current_user.related_id:
        flash('无权修改此开课的成绩', 'danger')
        return redirect(url_for('grade.list_offerings_for_grade'))

    enrollments = Enrollment.query.filter_by(offering_id=offering_id)\
        .filter(Enrollment.status != '退课').order_by(Enrollment.student_id).all()

    updated_count = inserted_count = 0
    parsed = []
    try:
        for enrollment in enrollments:
            sid = enrollment.student_id
            fields = [f'{name}_{sid}' for name in ('daily', 'midterm', 'final', 'makeup')]
            if not any(field in request.form for field in fields):
                continue  # A partial form must not erase omitted students' grades.
            if not all(field in request.form for field in fields):
                raise ValueError('成绩表字段不完整，请刷新后重试')
            scores = [parse_score(request.form.get(field)) for field in fields]
            status = request.form.get(f'status_{sid}', '正常')
            if status not in ('正常', '补考', '重修', '缓考', '缺考'):
                raise ValueError('无效成绩状态')
            parsed.append((enrollment, scores, status))
        # Pin the audit variable to this transaction before any flush; no commit here.
        set_audit_user()
        with db.session.no_autoflush:
            for enrollment, scores, status in parsed:
                enrollment = Enrollment.query.filter_by(enrollment_id=enrollment.enrollment_id).with_for_update().populate_existing().one()
                existing = Grade.query.filter_by(enrollment_id=enrollment.enrollment_id).with_for_update().populate_existing().first()
                before = snapshot(existing)
                if existing is None:
                    inserted_count += 1
                else:
                    updated_count += 1
                values = dict(zip(('daily_score', 'midterm_score', 'final_score', 'makeup_score'), scores))
                values['status'] = status
                grade = write_grade(enrollment, offering, values, gpa_function=score_to_gpa)
                db.session.flush()
                after = snapshot(grade)
                if before != after:
                    db.session.add(ChangeEvent(actor_id=current_user.user_id, source_type='manual',
                        entity='grade', entity_id=str(grade.grade_id), student_id=enrollment.student_id,
                        before=before, after=after, reason='成绩录入页面'))
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        flash(str(error), 'danger')
        return redirect(url_for('grade.entry_form', offering_id=offering_id))
    except Exception:
        db.session.rollback()
        raise

    flash(f'成绩保存成功！新增 {inserted_count} 条，更新 {updated_count} 条。', 'success')
    return redirect(url_for('grade.entry_form', offering_id=offering_id))


@grade_bp.route('/my', methods=['GET'])
@login_required
def my_grades():
    """Student views own grades. Admin/Counselor can search by student_id."""
    search_id = request.args.get('student_id', '').strip()
    if current_user.role == 'student':
        student_id = str(current_user.related_id)
    elif search_id:
        student_id = search_id
    else:
        # Admin/counselor must provide a student_id to search
        flash('请通过学生学号搜索成绩', 'info')
        return render_template('grade/my_grades.html',
                               enrollments=[],
                               student_gpa=None,
                               completed_credits=None,
                               semesters=[],
                               current_semester='')

    semester = request.args.get('semester', '')

    enrollments_query = Enrollment.query.filter_by(student_id=student_id)\
        .filter(Enrollment.status != '退课')\
        .join(CourseOffering).join(Course)

    if semester:
        enrollments_query = enrollments_query.filter(
            CourseOffering.semester == semester
        )

    enrollments = enrollments_query.order_by(
        CourseOffering.academic_year.desc(),
        CourseOffering.semester
    ).all()

    # Calculate current semester GPA
    student_gpa = get_student_gpa(student_id)
    completed_credits = get_completed_credits(student_id)

    # Get available semesters for filtering
    semesters = db.session.query(CourseOffering.semester)\
        .join(Enrollment)\
        .filter(Enrollment.student_id == student_id)\
        .distinct().order_by(CourseOffering.semester).all()

    return render_template('grade/my_grades.html',
                           enrollments=enrollments,
                           student_gpa=student_gpa,
                           completed_credits=completed_credits,
                           semesters=[s[0] for s in semesters],
                           current_semester=semester)


@grade_bp.route('/transcript', methods=['GET'])
@login_required
def transcript():
    """Student printable transcript. Admin/Counselor can view by student_id param."""
    search_id = request.args.get('student_id', '').strip()
    if current_user.role == 'student':
        student_id = str(current_user.related_id)
    elif search_id:
        student_id = search_id
    else:
        # Admin/counselor without a student_id — show search form
        return render_template('grade/transcript.html', student=None)
    student = Student.query.get_or_404(student_id)

    enrollments = Enrollment.query.filter_by(student_id=student_id)\
        .filter(Enrollment.status != '退课')\
        .join(CourseOffering).join(Course)\
        .filter(Enrollment.grade.has())\
        .order_by(CourseOffering.academic_year, CourseOffering.semester).all()

    student_gpa = get_student_gpa(student_id)
    completed_credits = get_completed_credits(student_id)

    # Get latest semester for ranking
    latest_enrollment = Enrollment.query.filter_by(student_id=student_id)\
        .join(CourseOffering)\
        .order_by(CourseOffering.academic_year.desc(), CourseOffering.semester.desc()).first()

    class_ranking = None
    if latest_enrollment:
        class_ranking = get_class_ranking(
            student_id,
            latest_enrollment.offering.academic_year,
            latest_enrollment.offering.semester
        )

    return render_template('grade/transcript.html',
                           student=student,
                           enrollments=enrollments,
                           student_gpa=student_gpa,
                           completed_credits=completed_credits,
                           class_ranking=class_ranking)


@grade_bp.route('/class/<int:class_id>', methods=['GET'])
@login_required
@role_required('admin')
def class_grades(class_id):
    """View class grade sheet."""
    class_ = Class.query.get_or_404(class_id)
    academic_year = request.args.get('academic_year', '')
    semester = request.args.get('semester', '')

    students = Student.query.filter_by(class_id=class_id)\
        .order_by(Student.student_id).all()

    # Build grade data per student
    student_grades = []
    for student in students:
        enrollments_query = Enrollment.query.filter_by(student_id=student.student_id)\
            .join(CourseOffering).join(Course)

        if academic_year:
            enrollments_query = enrollments_query.filter(
                CourseOffering.academic_year == academic_year
            )
        if semester:
            enrollments_query = enrollments_query.filter(
                CourseOffering.semester == semester
            )

        student_enrollments = enrollments_query.all()

        # Calculate average total_score for this student
        valid_scores = []
        for enr in student_enrollments:
            if enr.grade and enr.grade.total_score is not None:
                valid_scores.append(float(enr.grade.total_score))

        avg_score = round(sum(valid_scores) / len(valid_scores), 2) if valid_scores else None

        student_grades.append({
            'student': student,
            'avg_score': avg_score,
            'enrollments': student_enrollments,
            'count': len(student_enrollments)
        })

    # Get filters
    academic_years = db.session.query(CourseOffering.academic_year).distinct().order_by(
        CourseOffering.academic_year.desc()).all()
    semesters = db.session.query(CourseOffering.semester).distinct().order_by(
        CourseOffering.semester).all()

    return render_template('grade/class_grades.html',
                           class_=class_,
                           student_grades=student_grades,
                           academic_years=[ay[0] for ay in academic_years],
                           semesters=[s[0] for s in semesters],
                           current_academic_year=academic_year,
                           current_semester=semester)
