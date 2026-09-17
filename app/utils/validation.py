from datetime import date

from app.extensions import db
from app.models import Class


def validate_student(student):
    if not student.student_id or not student.name:
        raise ValueError('学号和姓名不能为空')
    if student.gender not in ('男', '女'):
        raise ValueError('性别无效')
    if student.status not in ('在读', '休学', '退学', '毕业', '肄业'):
        raise ValueError('学籍状态无效')
    if not 1900 <= student.enrollment_year <= date.today().year + 1:
        raise ValueError('入学年份无效')
    if not 1 <= student.education_length <= 10:
        raise ValueError('学制无效')
    if isinstance(student.birth_date, str):
        student.birth_date = date.fromisoformat(student.birth_date)
    with db.session.no_autoflush:
        class_ = db.session.get(Class, student.class_id)
        if not class_ or class_.major_id != student.major_id:
            raise ValueError('所选班级不属于所选专业')
