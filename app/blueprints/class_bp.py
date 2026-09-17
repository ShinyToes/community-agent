from app.utils.security import user_error_message
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.extensions import db
from app.models import Class, Major
from app.utils.decorators import admin_required

class_bp = Blueprint('class', __name__)


@class_bp.route('/')
@login_required
def list_classes():
    classes = Class.query.order_by(Class.class_id).all()
    return render_template('class/list.html', classes=classes)


@class_bp.route('/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_class():
    majors = Major.query.order_by(Major.major_name).all()
    if request.method == 'POST':
        try:
            cls = Class(
                class_name=request.form['class_name'].strip(),
                grade=int(request.form['grade']),
                counselor=request.form.get('counselor', '').strip() or None,
                major_id=int(request.form['major_id']),
            )
            db.session.add(cls)
            db.session.commit()
            flash('班级添加成功', 'success')
            return redirect(url_for('class.list_classes'))
        except Exception as e:
            db.session.rollback()
            flash(f'添加失败: {user_error_message(e)}', 'danger')
    return render_template('class/form.html', cls=None, majors=majors)


@class_bp.route('/<int:class_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_class(class_id):
    cls = Class.query.get_or_404(class_id)
    majors = Major.query.order_by(Major.major_name).all()
    if request.method == 'POST':
        try:
            cls.class_name = request.form['class_name'].strip()
            cls.grade = int(request.form['grade'])
            cls.counselor = request.form.get('counselor', '').strip() or None
            new_major_id = int(request.form['major_id'])
            if new_major_id != cls.major_id and cls.students.count():
                raise ValueError('班级已有学生，不能直接更换所属专业')
            cls.major_id = new_major_id
            db.session.commit()
            flash('班级修改成功', 'success')
            return redirect(url_for('class.list_classes'))
        except Exception as e:
            db.session.rollback()
            flash(f'修改失败: {user_error_message(e)}', 'danger')
    return render_template('class/form.html', cls=cls, majors=majors)


@class_bp.route('/<int:class_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_class(class_id):
    cls = Class.query.get_or_404(class_id)
    try:
        db.session.delete(cls)
        db.session.commit()
        flash('班级已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败(可能存在关联数据): {user_error_message(e)}', 'danger')
    return redirect(url_for('class.list_classes'))
