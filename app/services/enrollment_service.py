"""
Enrollment service.

Calls MySQL stored procedures and functions related to course enrollment:
- proc_EnrollStudent(p_student_id, p_offering_id, @result)
- fn_CheckCourseConflict(p_student_id, p_offering_id)
"""

from app.extensions import db
from sqlalchemy import text


def enroll_student(student_id, offering_id):
    """Call proc_EnrollStudent to enroll a student in a course offering.

    Args:
        student_id: The student's ID (string).
        offering_id: The course offering ID (int).

    Returns:
        (success: bool, message: str) — success is True when the message
        equals '选课成功', False otherwise.
    """
    db.session.execute(
        text("CALL proc_EnrollStudent(:sid, :oid, @result)"),
        {"sid": student_id, "oid": offering_id},
    )

    # 先读取存储过程返回的结果，再决定提交还是回滚
    row = db.session.execute(text("SELECT @result")).fetchone()
    raw = row[0] if row and row[0] else "选课失败，请稍后重试"

    # 翻译错误信息为用户友好提示
    messages = {
        "选课成功": "选课成功",
        "错误：学生不存在": "该学生不存在",
        "错误：课程容量已满": "课程名额已满，请选择其他课程",
        "错误：已选过该课程，不可重复选课": "您已选过该课程，无需重复选课",
        "错误：已选过该课程的其他时间段，不可重复选课": "您已选过该课程（其他时间段），无需重复选课",
        "错误：与已有课程时间冲突": "课程时间与您已有课程冲突，请调整选课",
        "错误：学籍状态为\"毕业\"，不允许选课": "当前学籍状态不允许选课",
        "错误：学籍状态为\"休学\"，不允许选课": "当前学籍状态不允许选课",
        "错误：学籍状态为\"退学\"，不允许选课": "当前学籍状态不允许选课",
    }
    friendly = messages.get(raw, f"选课失败: {raw}")

    is_success = raw == "选课成功"
    if is_success:
        db.session.commit()
    else:
        db.session.rollback()

    return is_success, friendly


def check_course_conflict(student_id, offering_id):
    """Call fn_CheckCourseConflict to determine if a student has a time conflict.

    Args:
        student_id: The student's ID (string).
        offering_id: The course offering ID (int).

    Returns:
        True if a conflict exists, False otherwise.
    """
    row = db.session.execute(
        text("SELECT fn_CheckCourseConflict(:sid, :oid)"),
        {"sid": student_id, "oid": offering_id},
    ).fetchone()
    return bool(row[0]) if row[0] is not None else False
