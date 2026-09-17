from flask import session
from flask_login import current_user
from app.extensions import db


def set_audit_user():
    """在成绩修改操作前，设置 MySQL 会话变量 @current_user_id
    trg_Grade_AfterUpdate 触发器依赖此变量"""
    if not current_user.is_authenticated:
        raise PermissionError('成绩修改需要已登录用户')
    if db.session.get_bind().dialect.name != 'mysql':
        return
    user_id = current_user.user_id
    db.session.execute(db.text("SET @current_user_id = :uid"), {"uid": user_id})
