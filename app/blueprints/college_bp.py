from app.utils.security import user_error_message
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.extensions import db
from app.models import College
from app.utils.decorators import admin_required

college_bp = Blueprint('college', __name__)


@college_bp.route('/')
@login_required
def list_colleges():
    colleges = College.query.order_by(College.college_id).all()
    return render_template('college/list.html', colleges=colleges)


@college_bp.route('/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_college():
    if request.method == 'POST':
        try:
            college = College(
                college_code=request.form['college_code'].strip(),
                college_name=request.form['college_name'].strip(),
                dean=request.form.get('dean', '').strip() or None,
                office=request.form.get('office', '').strip() or None,
                phone=request.form.get('phone', '').strip() or None,
            )
            db.session.add(college)
            db.session.commit()
            flash('学院添加成功', 'success')
            return redirect(url_for('college.list_colleges'))
        except Exception as e:
            db.session.rollback()
            flash(f'添加失败: {user_error_message(e)}', 'danger')
    return render_template('college/form.html', college=None)


@college_bp.route('/<int:college_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_college(college_id):
    college = College.query.get_or_404(college_id)
    if request.method == 'POST':
        try:
            college.college_code = request.form['college_code'].strip()
            college.college_name = request.form['college_name'].strip()
            college.dean = request.form.get('dean', '').strip() or None
            college.office = request.form.get('office', '').strip() or None
            college.phone = request.form.get('phone', '').strip() or None
            db.session.commit()
            flash('学院修改成功', 'success')
            return redirect(url_for('college.list_colleges'))
        except Exception as e:
            db.session.rollback()
            flash(f'修改失败: {user_error_message(e)}', 'danger')
    return render_template('college/form.html', college=college)


@college_bp.route('/<int:college_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_college(college_id):
    college = College.query.get_or_404(college_id)
    try:
        db.session.delete(college)
        db.session.commit()
        flash('学院已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败(可能存在关联数据): {user_error_message(e)}', 'danger')
    return redirect(url_for('college.list_colleges'))
