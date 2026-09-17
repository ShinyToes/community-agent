from functools import wraps
from flask import abort, current_app
from flask_login import current_user


def role_required(*roles):
    """限制访问权限: @role_required('admin') 或 @role_required('student')"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    """仅管理员可访问"""
    return role_required('admin')(f)
