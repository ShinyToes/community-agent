"""
Grade service.

Calls MySQL stored functions related to grades and GPA:
- fn_ScoreToGPA(p_score)             -> DECIMAL(3,1)
- fn_GetStudentGPA(p_student_id)     -> DECIMAL(4,2)
- fn_GetClassRanking(p_student_id, p_academic_year, p_semester) -> INT
- fn_GetCompletedCredits(p_student_id) -> DECIMAL(5,1)
"""

from app.extensions import db
from sqlalchemy import text
from decimal import Decimal


def score_to_gpa(score):
    """Convert a numeric score to its GPA equivalent.

    Args:
        score: Numeric score value.

    Returns:
        GPA value as a Decimal, or None if the function returns NULL.
    """
    row = db.session.execute(
        text("SELECT fn_ScoreToGPA(:score)"),
        {"score": score},
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def get_student_gpa(student_id):
    """Get the overall GPA for a student.

    Args:
        student_id: The student's ID (string).

    Returns:
        GPA value as a Decimal, or None if the function returns NULL.
    """
    row = db.session.execute(
        text("SELECT fn_GetStudentGPA(:sid)"),
        {"sid": student_id},
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def get_class_ranking(student_id, academic_year, semester):
    """Get a student's class ranking for a given academic period.

    Args:
        student_id: The student's ID (string).
        academic_year: Academic year string (e.g. '2025-2026').
        semester: Semester string (e.g. '第一学期', '第二学期').

    Returns:
        Ranking as an integer, or None if the function returns NULL.
    """
    row = db.session.execute(
        text("SELECT fn_GetClassRanking(:sid, :year, :sem)"),
        {"sid": student_id, "year": academic_year, "sem": semester},
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def get_completed_credits(student_id):
    """Get the total completed credits for a student.

    Args:
        student_id: The student's ID (string).

    Returns:
        Completed credits as a Decimal, or None if the function returns NULL.
    """
    row = db.session.execute(
        text("SELECT fn_GetCompletedCredits(:sid)"),
        {"sid": student_id},
    ).fetchone()
    return row[0] if row and row[0] is not None else None
