import hashlib
import hmac
import time
from functools import wraps

from flask import abort, current_app, request
from flask_login import current_user
from sqlalchemy import select

from .extensions import db
from .models import AuthRateBucket


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.role != 'admin':
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def consume_auth_attempt(action):
    """Atomic shared fixed-window counter; do not trust forwarded client headers."""
    window = int(time.time()) // current_app.config['AUTH_RATE_WINDOW']
    key = hmac.new(current_app.secret_key.encode(),
                   f'{action}:{request.remote_addr or "unknown"}'.encode(),
                   hashlib.sha256).hexdigest()
    dialect = db.engine.dialect.name
    if dialect == 'mysql':
        from sqlalchemy.dialects.mysql import insert
        stmt = insert(AuthRateBucket).values(key=key, window=window, count=1)
        stmt = stmt.on_duplicate_key_update(count=AuthRateBucket.count + 1)
    else:
        from sqlalchemy.dialects.sqlite import insert
        stmt = insert(AuthRateBucket).values(key=key, window=window, count=1)
        stmt = stmt.on_conflict_do_update(index_elements=['key', 'window'],
                                         set_={'count': AuthRateBucket.count + 1})
    # Independent transaction: a failed login must not undo its rate counter.
    with db.engine.begin() as connection:
        connection.execute(stmt)
        count = connection.execute(select(AuthRateBucket.count).where(
            AuthRateBucket.key == key, AuthRateBucket.window == window)).scalar_one()
    if count > current_app.config[f'{action.upper()}_RATE_LIMIT']:
        abort(429)
