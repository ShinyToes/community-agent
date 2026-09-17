import re

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .models import AuditEvent, User
from .security import consume_auth_attempt

bp = Blueprint('auth', __name__, url_prefix='/auth')
# Same algorithm/work factor for unknown accounts, without exposing user existence.
DUMMY_HASH = generate_password_hash('not-a-real-account-password')


def credentials():
    data = request.get_json() if request.is_json else request.form
    if not isinstance(data, dict) and not hasattr(data, 'get'):
        abort(400)
    username, password = data.get('username'), data.get('password')
    if not isinstance(username, str) or not isinstance(password, str):
        abort(400)
    username = username.strip().lower()
    if not re.fullmatch(r'[a-z0-9_]{3,32}', username) or not 6 <= len(password) <= 128:
        abort(400, description='用户名需为 3–32 位字母、数字或下划线，密码需为 6–128 个字符。')
    return username, password


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('auth.html', register=True)
    consume_auth_attempt('register')
    username, password = credentials()
    user = User(username=username, password_hash=generate_password_hash(password), role='member')
    db.session.add(user)
    try:
        db.session.flush()
        db.session.add(AuditEvent(actor_id=user.id, target_id=user.id,
                                  action='register', reason='用户注册'))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if not request.is_json:
            return render_template('auth.html', register=True, username=username,
                                   form_error='该用户名已被使用，请换一个用户名。'), 409
        abort(409, description='该用户名已被使用。')
    session.clear()
    login_user(user)
    session.permanent = True
    if request.is_json:
        return jsonify(id=user.id, username=user.username, role=user.role), 201
    return redirect(url_for('index'), code=303)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('auth.html', register=False)
    consume_auth_attempt('login')
    username, password = credentials()
    user = db.session.scalar(select(User).where(User.username == username))
    valid = check_password_hash(user.password_hash if user else DUMMY_HASH, password)
    if not user or not valid or not user.active:
        abort(401, description='用户名或密码错误，或账号不可用。')
    session.clear()
    login_user(user)
    session.permanent = True
    if request.is_json:
        return jsonify(id=user.id, username=user.username, role=user.role)
    return redirect(url_for('index'), code=303)


@bp.post('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return ('', 204) if request.is_json else redirect(url_for('index'), code=303)


@bp.get('/me')
@login_required
def me():
    return jsonify(id=current_user.id, username=current_user.username, role=current_user.role)
