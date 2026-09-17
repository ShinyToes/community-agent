"""Resource authorization shared by HTML routes and future Agent tools."""
from urllib.parse import urlsplit

from flask import abort, request
from flask_login import current_user


def require_student_access(student_id):
    if not current_user.is_authenticated:
        abort(401)
    if current_user.role == 'admin':
        return
    if (current_user.role == 'student' and current_user.related_id
            and str(current_user.related_id) == str(student_id)):
        return
    abort(403)


def safe_redirect_target(value):
    # Accept local paths only, including when a caller supplies a Referer URL.
    if not value or any(ord(c) < 32 for c in value) or '\\' in value:
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return None
    return value if value.startswith('/') and not value.startswith('//') else None


def user_error_message(error):
    # SQL exception strings can include bound parameters and personal information.
    return str(error) if isinstance(error, ValueError) else '操作失败，请检查输入或关联数据后重试'


def register_security(app):
    @app.before_request
    def protect_legacy_uploads_and_roles():
        # Old uploads remain on disk for compatibility, but never publicly served.
        if request.endpoint == 'static':
            name = (request.view_args or {}).get('filename', '').replace('\\', '/')
            if 'uploads' in name.lower().split('/'):
                abort(404)
        if (current_user.is_authenticated and current_user.role not in ('admin', 'student')
                and request.endpoint != 'auth.logout'):
            abort(403)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response
