from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models import AuditLog
from functools import wraps

audit_bp = Blueprint('audit', __name__, url_prefix='/audit')


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.role != 'admin':
            flash('您没有权限访问此页面。', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


@audit_bp.route('/')
@login_required
@admin_required
def list_logs():
    page = request.args.get('page', 1, type=int)
    table_name = request.args.get('table_name', '').strip()
    action = request.args.get('action', '').strip()
    user_id = request.args.get('user_id', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    query = AuditLog.query

    if table_name:
        query = query.filter(AuditLog.table_name.like(f'%{table_name}%'))
    if action:
        query = query.filter(AuditLog.action == action)
    if user_id:
        query = query.filter(AuditLog.user_id.like(f'%{user_id}%'))
    if date_from:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AuditLog.created_at <= date_to + ' 23:59:59')

    query = query.order_by(AuditLog.created_at.desc())

    pagination = query.paginate(page=page, per_page=25, error_out=False)
    logs = pagination.items

    return render_template('audit/list.html', logs=logs, pagination=pagination)
