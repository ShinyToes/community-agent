"""Private attachments. Caller owns the database transaction."""
from pathlib import Path
import uuid

from flask import abort, current_app
from flask_login import current_user
from sqlalchemy import event
from sqlalchemy.orm import Session
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import File, Student, MajorChange, RewardPunishment, PhysicalExam
from app.utils.security import require_student_access

RELATED_MODELS = {
    'student': Student, 'major_change': MajorChange,
    'reward_punishment': RewardPunishment, 'physical_exam': PhysicalExam,
}
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.txt', '.csv', '.xlsx', '.docx'}


def authorize_record(table, record_id, *, write=False):
    model = RELATED_MODELS.get(table)
    if model is None:
        abort(400, description='不支持的附件关联类型')
    if table != 'student':
        try:
            record_id = int(record_id)
        except (ValueError, TypeError):
            abort(400)
    record = db.session.get(model, record_id)
    if record is None:
        abort(404)
    require_student_access(record.student_id)
    # Students may attach evidence to their own pending application only.
    if write and current_user.role != 'admin':
        if table != 'major_change' or record.approval_status != '待审批':
            abort(403)
    return record


def resolve_file_path(file_record):
    value = file_record.file_path.replace('\\', '/')
    if value.startswith('private/'):
        root = Path(current_app.config['UPLOAD_FOLDER']).resolve()
        relative = value[len('private/'):]
    elif value.startswith('uploads/'):
        # Legacy files are served exclusively through authorized routes.
        root = (Path(current_app.static_folder) / 'uploads').resolve()
        relative = value[len('uploads/'):]
    else:
        abort(400, description='无效附件路径')
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target == root:
        abort(400, description='无效附件路径')
    return target


def _cleanup(paths):
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            current_app.logger.error('Attachment cleanup failed; reconcile storage before reuse')


@event.listens_for(Session, 'after_commit')
def _files_after_commit(session):
    session.info.pop('new_uploads', None)
    _cleanup(session.info.pop('deleted_uploads', []))


@event.listens_for(Session, 'after_rollback')
def _files_after_rollback(session):
    session.info.pop('deleted_uploads', None)
    _cleanup(session.info.pop('new_uploads', []))


def save_uploaded_file(uploaded_file, related_table, related_id):
    authorize_record(related_table, related_id, write=True)
    name = uploaded_file.filename or ''
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError('不支持的文件类型；请上传图片、PDF、TXT、CSV、XLSX 或 DOCX')
    if len(name) > 255:
        raise ValueError('文件名过长')
    root = Path(current_app.config['UPLOAD_FOLDER']).resolve()
    root.mkdir(parents=True, exist_ok=True)
    filename = uuid.uuid4().hex + ext
    path = root / filename
    db.session.info.setdefault('new_uploads', []).append(path)
    uploaded_file.save(path)
    record = File(
        file_name=secure_filename(name) or ('attachment' + ext),
        file_type='image' if ext in {'.jpg', '.jpeg', '.png', '.gif', '.webp'} else 'document',
        file_path='private/' + filename,
        related_table=related_table, related_id=str(related_id), file_size=path.stat().st_size,
    )
    db.session.add(record)
    db.session.flush()
    return record


def get_files_for_record(table_name, record_id):
    authorize_record(table_name, record_id)
    return File.query.filter_by(related_table=table_name, related_id=str(record_id)).order_by(File.upload_time.desc()).all()


def delete_file_record(file_id):
    record = db.session.get(File, file_id)
    if record is None:
        return False
    authorize_record(record.related_table, record.related_id, write=True)
    db.session.info.setdefault('deleted_uploads', []).append(resolve_file_path(record))
    if record.related_table == 'student':
        student = db.session.get(Student, record.related_id)
        if student and student.photo == record.file_path:
            student.photo = None
    db.session.delete(record)
    db.session.flush()
    return True
