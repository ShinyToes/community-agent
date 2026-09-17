from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models import Student, Class, Major, Grade, Course, Enrollment, College, CourseOffering
from app.extensions import db
from sqlalchemy import func
from app.services.graduation_service import graduate_audit
from app.services.grade_service import get_completed_credits, get_student_gpa
from functools import wraps
from app.utils.decorators import admin_required

statistics_bp = Blueprint('statistics', __name__)

@statistics_bp.before_request
@login_required
@admin_required
def authorize_statistics():
    pass



def admin_or_counselor_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.role not in ('admin', 'counselor'):
            flash('您没有权限访问此页面。', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


@statistics_bp.route('/student-status')
@login_required
@admin_or_counselor_required
def student_status():
    total_students = Student.query.count()
    active_students = Student.query.filter(Student.status.in_(['在读','休学'])).count()
    total_majors = Major.query.count()
    total_classes = Class.query.count()
    return render_template('statistics/student_status.html',
                           total_students=total_students, active_students=active_students,
                           total_majors=total_majors, total_classes=total_classes)


@statistics_bp.route('/grade-distribution')
@login_required
@admin_or_counselor_required
def grade_distribution():
    colleges = College.query.order_by(College.college_name).all()
    majors = Major.query.order_by(Major.major_name).all()
    years = [r[0] for r in db.session.query(Student.enrollment_year).distinct().order_by(Student.enrollment_year.desc()).all()]
    return render_template('statistics/grade_distribution.html', colleges=colleges, majors=majors, years=years)


@statistics_bp.route('/graduation-audit', methods=['GET', 'POST'])
@login_required
@admin_or_counselor_required
def graduation_audit():
    if request.method == 'POST':
        class_id = request.form.get('class_id', '').strip()
        major_id = request.form.get('major_id', '').strip()
        if not class_id and not major_id:
            flash('请选择班级或专业。', 'warning')
            return redirect(url_for('statistics.graduation_audit'))
        query = Student.query
        if class_id: query = query.filter(Student.class_id == class_id)
        elif major_id: query = query.filter(Student.major_id == major_id)
        students = query.order_by(Student.student_id).all()
        results = []; qc = 0; uc = 0
        for student in students:
            qualified, message = graduate_audit(student.student_id)
            is_qualified = bool(qualified)
            if is_qualified: qc += 1
            else: uc += 1
            credits = get_completed_credits(student.student_id)
            gpa = get_student_gpa(student.student_id)
            fc = Enrollment.query.join(CourseOffering).join(Course)\
                .filter(Enrollment.student_id == student.student_id, Course.course_type == '必修', Enrollment.status == '未通过').count()
            results.append({'student_id': student.student_id, 'name': student.name,
                'major': student.major.major_name if student.major else '',
                'class': student.class_.class_name if student.class_ else '',
                'total_credits': float(credits) if credits else 0,
                'cumulative_gpa': float(gpa) if gpa else 0,
                'failed_required_count': fc, 'qualified': is_qualified, 'message': message})
        classes = Class.query.order_by(Class.class_name).all()
        majors = Major.query.order_by(Major.major_name).all()
        return render_template('statistics/graduation_audit.html', results=results,
                               total_students=len(results), qualified_count=qc, unqualified_count=uc,
                               classes=classes, majors=majors)
    classes = Class.query.order_by(Class.class_name).all()
    majors = Major.query.order_by(Major.major_name).all()
    return render_template('statistics/graduation_audit.html', results=None, classes=classes, majors=majors)


@statistics_bp.route('/api/student-status')
@login_required
def api_student_status():
    statuses = {}
    for s in Student.query.all():
        st = s.status or '未知'
        statuses[st] = statuses.get(st, 0) + 1
    return jsonify({'labels': list(statuses.keys()), 'values': list(statuses.values())})


@statistics_bp.route('/api/major-stats')
@login_required
def api_major_stats():
    majors = Major.query.order_by(Major.major_name).all()
    return jsonify({'labels': [m.major_name for m in majors],
                    'values': [Student.query.filter_by(major_id=m.major_id).count() for m in majors]})


@statistics_bp.route('/api/grade-distribution')
@login_required
def api_grade_distribution():
    year = request.args.get('year', '').strip()
    college_id = request.args.get('college_id', '').strip()
    major_id = request.args.get('major_id', '').strip()

    # 一次查所有相关成绩：学生 + 课程学分 + 总评
    q = db.session.query(Student.student_id, Course.credits, Grade.total_score)\
        .join(Enrollment, Enrollment.student_id == Student.student_id)\
        .join(Grade, Grade.enrollment_id == Enrollment.enrollment_id)\
        .join(CourseOffering, Enrollment.offering_id == CourseOffering.offering_id)\
        .join(Course, CourseOffering.course_id == Course.course_id)\
        .join(Major, Student.major_id == Major.major_id)\
        .filter(Grade.total_score.isnot(None))
    if year: q = q.filter(Student.enrollment_year == int(year))
    if college_id: q = q.filter(Major.college_id == int(college_id))
    if major_id: q = q.filter(Student.major_id == int(major_id))

    # 按学生分组计算加权平均
    student_scores = {}
    for sid, credits, score in q.all():
        w = float(credits) if credits else 0
        s = float(score) if score else 0
        if sid not in student_scores:
            student_scores[sid] = {'wsum': 0, 'wtotal': 0}
        student_scores[sid]['wsum'] += s * w
        student_scores[sid]['wtotal'] += w

    bins = ['0-59', '60-69', '70-79', '80-89', '90-100']
    counts = [0] * 5
    for d in student_scores.values():
        if d['wtotal'] > 0:
            avg = d['wsum'] / d['wtotal']
            if avg < 60: counts[0] += 1
            elif avg < 70: counts[1] += 1
            elif avg < 80: counts[2] += 1
            elif avg < 90: counts[3] += 1
            else: counts[4] += 1

    return jsonify({'labels': bins, 'values': counts})


@statistics_bp.route('/api/major-gpa')
@login_required
def api_major_gpa():
    year = request.args.get('year', '').strip()
    major_id = request.args.get('major_id', '').strip()

    # 每个学生的加权平均GPA，再求所有学生的平均
    q = db.session.query(Student.student_id, Course.credits, Grade.gpa)\
        .join(Enrollment, Enrollment.student_id == Student.student_id)\
        .join(Grade, Grade.enrollment_id == Enrollment.enrollment_id)\
        .join(CourseOffering, Enrollment.offering_id == CourseOffering.offering_id)\
        .join(Course, CourseOffering.course_id == Course.course_id)\
        .filter(Grade.gpa.isnot(None))
    if year: q = q.filter(Student.enrollment_year == int(year))
    if major_id: q = q.filter(Student.major_id == int(major_id))

    per_student = {}
    for sid, credits, gpa in q.all():
        w = float(credits) if credits else 0
        g = float(gpa) if gpa else 0
        if sid not in per_student:
            per_student[sid] = {'wsum': 0, 'wtotal': 0}
        per_student[sid]['wsum'] += g * w
        per_student[sid]['wtotal'] += w

    student_gpas = [d['wsum']/d['wtotal'] for d in per_student.values() if d['wtotal'] > 0]
    avg_gpa = sum(student_gpas) / len(student_gpas) if student_gpas else 0
    major_name = Major.query.get_or_404(int(major_id)).major_name if major_id else ''
    return jsonify({'label': major_name, 'value': round(avg_gpa, 2)})


@statistics_bp.route('/api/scatter')
@login_required
def api_scatter():
    courses = Course.query.order_by(Course.course_id).all()
    data = []
    for i, course in enumerate(courses):
        grades = Grade.query.join(Enrollment).join(CourseOffering)\
            .filter(CourseOffering.course_id == course.course_id).all()
        scores = [float(g.total_score) for g in grades if g.total_score is not None]
        if scores:
            avg = sum(scores) / len(scores)
            data.append({'x': i + 1, 'y': round(avg, 2), 'course': course.course_name})
    return jsonify(data)
