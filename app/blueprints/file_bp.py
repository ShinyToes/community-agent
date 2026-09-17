from flask import Blueprint, request, jsonify, flash, redirect, url_for, send_file, abort
from flask_login import login_required
from app.extensions import db
from app.models import File, Student
from app.services.file_service import (
    save_uploaded_file, delete_file_record, get_files_for_record,
    authorize_record, resolve_file_path,
)
from app.utils.security import safe_redirect_target, require_student_access

file_bp = Blueprint('file', __name__)


def back():
    return redirect(safe_redirect_target(request.referrer) or url_for('student.list_students'))


@file_bp.route('/upload/<table>/<record_id>', methods=['POST'])
@login_required
def upload_file(table, record_id):
    authorize_record(table, record_id, write=True)
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return jsonify(success=False, message='请选择文件'), 400
    try:
        record = save_uploaded_file(uploaded, table, record_id)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        return jsonify(success=False, message=str(error)), 400
    except Exception:
        db.session.rollback()
        raise
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(success=True, message='文件上传成功', file={
            'file_id': record.file_id, 'file_name': record.file_name,
            'file_size': record.file_size, 'upload_time': record.upload_time.strftime('%Y-%m-%d %H:%M'),
        })
    flash('文件上传成功', 'success')
    return back()


@file_bp.route('/<int:file_id>/download')
@login_required
def download_file(file_id):
    record = db.get_or_404(File, file_id)
    authorize_record(record.related_table, record.related_id)
    path = resolve_file_path(record)
    if not path.is_file():
        abort(404)
    return send_file(path, download_name=record.file_name, as_attachment=True)


@file_bp.route('/photo/<student_id>')
@login_required
def student_photo(student_id):
    require_student_access(student_id)
    student = db.get_or_404(Student, student_id)
    record = File.query.filter_by(related_table='student', related_id=student_id, file_path=student.photo).first_or_404()
    path = resolve_file_path(record)
    if path.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.gif', '.webp'} or not path.is_file():
        abort(404)
    return send_file(path)


@file_bp.route('/<int:file_id>/delete', methods=['POST'])
@login_required
def delete_file(file_id):
    record = db.get_or_404(File, file_id)
    authorize_record(record.related_table, record.related_id, write=True)
    delete_file_record(file_id)
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(success=True, message='文件已删除')
    flash('文件已删除', 'success')
    return back()


@file_bp.route('/list/<table>/<record_id>')
@login_required
def list_files(table, record_id):
    files = get_files_for_record(table, record_id)
    return jsonify([{
        'file_id': f.file_id, 'file_name': f.file_name, 'file_type': f.file_type,
        'file_size': f.file_size, 'upload_time': f.upload_time.strftime('%Y-%m-%d %H:%M') if f.upload_time else '',
    } for f in files])
