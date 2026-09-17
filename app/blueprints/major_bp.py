from app.utils.security import user_error_message
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.extensions import db
from app.models import Major, College
from app.utils.decorators import admin_required

major_bp = Blueprint('major', __name__)


@major_bp.route('/')
@login_required
def list_majors():
    majors = Major.query.order_by(Major.major_id).all()
    return render_template('major/list.html', majors=majors)


@major_bp.route('/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_major():
    colleges = College.query.order_by(College.college_name).all()
    if request.method == 'POST':
        try:
            major = Major(
                major_code=request.form['major_code'].strip(),
                major_name=request.form['major_name'].strip(),
                duration=int(request.form.get('duration', 4)),
                degree_type=request.form['degree_type'].strip(),
                college_id=int(request.form['college_id']),
            )
            db.session.add(major)
            db.session.commit()
            flash('专业添加成功', 'success')
            return redirect(url_for('major.list_majors'))
        except Exception as e:
            db.session.rollback()
            flash(f'添加失败: {user_error_message(e)}', 'danger')
    return render_template('major/form.html', major=None, colleges=colleges)


@major_bp.route('/<int:major_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_major(major_id):
    major = Major.query.get_or_404(major_id)
    colleges = College.query.order_by(College.college_name).all()
    if request.method == 'POST':
        try:
            major.major_code = request.form['major_code'].strip()
            major.major_name = request.form['major_name'].strip()
            major.duration = int(request.form.get('duration', 4))
            major.degree_type = request.form['degree_type'].strip()
            major.college_id = int(request.form['college_id'])
            db.session.commit()
            flash('专业修改成功', 'success')
            return redirect(url_for('major.list_majors'))
        except Exception as e:
            db.session.rollback()
            flash(f'修改失败: {user_error_message(e)}', 'danger')
    return render_template('major/form.html', major=major, colleges=colleges)


@major_bp.route('/<int:major_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_major(major_id):
    major = Major.query.get_or_404(major_id)
    try:
        db.session.delete(major)
        db.session.commit()
        flash('专业已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败(可能存在关联数据): {user_error_message(e)}', 'danger')
    return redirect(url_for('major.list_majors'))
