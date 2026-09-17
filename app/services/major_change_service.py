"""
Major change service.

Calls MySQL stored procedure:
- proc_ChangeMajor(p_student_id, p_new_major_id, p_new_class_id,
                   p_reason, p_attachment, @result) -> (bool, str)
"""

from app.extensions import db
from sqlalchemy import text


def change_major(student_id, new_major_id, new_class_id, reason, attachment=None):
    """Call proc_ChangeMajor to process a major change request.

    Args:
        student_id: The student's ID (string).
        new_major_id: The target major ID (int).
        new_class_id: The target class ID (int).
        reason: Reason for the change (string).
        attachment: Optional attachment filename/path (string or None).

    Returns:
        (success: bool, message: str) — success is True when the message
        equals '转专业成功', False otherwise.
    """
    db.session.execute(
        text("CALL proc_ChangeMajor(:sid, :mid, :cid, :reason, :att, @result)"),
        {
            "sid": student_id,
            "mid": new_major_id,
            "cid": new_class_id,
            "reason": reason,
            "att": attachment,
        },
    )

    # 先读取存储过程返回的结果，再决定提交还是回滚
    row = db.session.execute(text("SELECT @result")).fetchone()
    raw = row[0] if row and row[0] else "未知错误"

    # 存储过程可能返回多种成功消息
    success_messages = ["专业变更成功", "转专业成功", "success"]
    is_success = any(msg in (raw or "") for msg in success_messages)

    if is_success:
        db.session.commit()
    else:
        db.session.rollback()

    return is_success, raw
