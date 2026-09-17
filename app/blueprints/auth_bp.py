from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models import User
from app.utils.security import safe_redirect_target

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.is_active:
                flash('账户已被禁用，请联系管理员', 'danger')
                return render_template('auth/login.html')

            login_user(user)
            user.last_login = datetime.utcnow()
            db.session.commit()
            flash(f'欢迎回来，{username}！', 'success')

            next_page = safe_redirect_target(request.args.get('next'))
            return redirect(next_page or url_for('index'))
        else:
            flash('用户名或密码错误', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('您已安全退出', 'info')
    return redirect(url_for('auth.login'))
