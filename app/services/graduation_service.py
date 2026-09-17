"""
Graduation audit service.

Calls MySQL stored procedures:
- proc_GraduateAudit(p_student_id, @qualified, @message) -> (int, str)
- proc_CalculateStudentGPA(p_student_id, p_academic_year, p_semester) -> result set
"""

from app.extensions import db
from sqlalchemy import text
from decimal import Decimal


def graduate_audit(student_id):
    """Call proc_GraduateAudit to check whether a student meets graduation requirements.

    Args:
        student_id: The student's ID (string).

    Returns:
        (qualified: int, message: str) — qualified is 1 if the student
        meets requirements, 0 otherwise.
    """
    db.session.execute(
        text("CALL proc_GraduateAudit(:sid, @qualified, @message)"),
        {"sid": student_id},
    )

    # 先读取 OUT 参数再提交
    row = db.session.execute(
        text("SELECT @qualified, @message")
    ).fetchone()
    db.session.commit()

    return int(row[0]) if row[0] is not None else 0, row[1] or ""


def calculate_student_gpa(student_id, academic_year, semester):
    """Call proc_CalculateStudentGPA to compute GPA for a given period.

    The procedure returns a result set. This function fetches and returns it.

    Args:
        student_id: The student's ID (string).
        academic_year: Academic year string (e.g. '2025-2026').
        semester: Semester string (e.g. '第一学期', '第二学期').

    Returns:
        List of row proxies from the procedure's result set.
    """
    result = db.session.execute(
        text("CALL proc_CalculateStudentGPA(:sid, :year, :sem)"),
        {"sid": student_id, "year": academic_year, "sem": semester},
    )
    # 先获取结果集再提交（存储过程的结果集必须在 commit 前读取）
    rows = result.fetchall()
    db.session.commit()
    return rows
