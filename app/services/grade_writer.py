"""Shared grade mutation; never commits. Caller locks offering then enrollment."""
from decimal import Decimal
from app.extensions import db
from app.models import Grade
from app.services.grade_validation import parse_score, weighted_total

GRADE_FIELDS = ('daily_score', 'midterm_score', 'final_score', 'makeup_score')
THRESHOLDS = ((95, '4.3'), (90, '4.0'), (85, '3.7'), (82, '3.3'), (78, '3.0'),
              (75, '2.7'), (72, '2.3'), (68, '2.0'), (65, '1.7'), (64, '1.5'),
              (61, '1.3'), (60, '1.0'))


def score_gpa(score):
    return next((Decimal(gpa) for threshold, gpa in THRESHOLDS if score >= threshold), Decimal(0))


def write_grade(enrollment, offering, values, gpa_function=score_gpa):
    if enrollment.status == '退课':
        raise ValueError('已退课，不能修改成绩')
    grade = enrollment.grade
    if grade is None:
        grade = Grade(enrollment_id=enrollment.enrollment_id, status='正常')
        db.session.add(grade)
    for field in GRADE_FIELDS:
        if field in values:
            setattr(grade, field, parse_score(values[field]))
    status = values.get('status', grade.status or '正常')
    if status not in ('正常', '补考', '重修', '缓考', '缺考'):
        raise ValueError('无效成绩状态')
    grade.status = status
    grade.total_score = weighted_total(
        (grade.daily_score, grade.midterm_score, grade.final_score),
        (offering.daily_weight, offering.midterm_weight, offering.final_weight))
    grade.gpa = gpa_function(grade.total_score) if grade.total_score is not None else None
    if grade.total_score is None or status == '缓考':
        enrollment.status = '在修'
    elif status == '缺考':
        enrollment.status = '未通过'
    else:
        passed = grade.total_score >= 60 or (grade.makeup_score is not None and grade.makeup_score >= 60)
        enrollment.status = '已通过' if passed else '未通过'
    return grade
