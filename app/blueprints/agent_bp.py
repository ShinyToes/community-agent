import json
from pathlib import Path
from flask import Blueprint, request, jsonify, render_template, send_file, current_app
from flask_login import login_required, current_user

from app.extensions import db
from app.agent_models import (Conversation, AgentMessage, ImportBatch, ImportRow,
                              Document, ChangeDraft, ChangeEvent)
from app.agent.runtime import respond, owned_conversation
from app.agent.tools import confirm_draft, query_data
from app.services.imports.workflow import (create_batch, owned_batch, revalidate, commit_batch,
                                         require_admin, Conflict)
from app.services.imports.profiles import FIELDS

agent_bp = Blueprint('agent', __name__)


@agent_bp.before_request
@login_required
def authenticate():
    pass


@agent_bp.errorhandler(ValueError)
@agent_bp.errorhandler(PermissionError)
@agent_bp.errorhandler(LookupError)
def invalid(error):
    db.session.rollback()
    code = 409 if isinstance(error, Conflict) else 403 if isinstance(error, PermissionError) else 404 if isinstance(error, LookupError) else 400
    return jsonify(error=str(error)), code


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('需要JSON对象')
    return data


@agent_bp.get('/agent')
def workspace():
    return render_template('agent/workspace.html')


@agent_bp.post('/agent/conversations')
def new_conversation():
    conversation = Conversation(owner_id=current_user.user_id, role_scope=current_user.role,
                                subject_scope=current_user.related_id)
    db.session.add(conversation)
    db.session.commit()
    return jsonify(id=conversation.id)


@agent_bp.get('/agent/conversations/<conversation_id>')
def get_conversation(conversation_id):
    owned_conversation(conversation_id, current_user)
    messages = AgentMessage.query.filter_by(conversation_id=conversation_id).order_by(AgentMessage.id).limit(100).all()
    return jsonify(messages=[{'role': m.role, 'content': m.content, 'result': m.result} for m in messages])


@agent_bp.post('/agent/conversations/<conversation_id>/messages')
def send_message(conversation_id):
    return jsonify(respond(conversation_id, payload().get('text'), current_user))


@agent_bp.post('/agent/query')
def query():
    """Structured fallback, subject to the same permissions as Agent tools."""
    data = payload()
    return jsonify(query_data(current_user, data.get('kind'), data.get('filters', {})))


@agent_bp.post('/agent/drafts/<draft_id>/confirm')
def confirm(draft_id):
    return jsonify(confirm_draft(draft_id, current_user))


@agent_bp.post('/agent/drafts/<draft_id>/cancel')
def cancel_draft(draft_id):
    require_admin(current_user)
    draft = ChangeDraft.query.filter_by(id=draft_id, owner_id=current_user.user_id).with_for_update().first()
    if not draft:
        raise LookupError('草稿不存在')
    if draft.status != 'pending':
        raise Conflict('草稿已处理')
    draft.status = 'cancelled'
    db.session.commit()
    return jsonify(status='cancelled')


@agent_bp.post('/imports')
def upload():
    file = request.files.get('file')
    if not file or not file.filename:
        raise ValueError('请选择文件')
    try:
        options = json.loads(request.form.get('options', '{}'))
    except json.JSONDecodeError:
        raise ValueError('选项必须是JSON对象') from None
    if not isinstance(options, dict):
        raise ValueError('选项必须是对象')
    batch = create_batch(file, request.form.get('kind'), options, current_user)
    return jsonify(id=batch.id, status=batch.status), 202


@agent_bp.get('/imports')
def list_imports():
    require_admin(current_user)
    batches = ImportBatch.query.filter_by(owner_id=current_user.user_id).order_by(ImportBatch.created_at.desc()).limit(50).all()
    return jsonify(batches=[{'id': b.id, 'kind': b.kind, 'status': b.status, 'name': b.document.name} for b in batches])


@agent_bp.get('/imports/<batch_id>')
def batch_detail(batch_id):
    batch = owned_batch(batch_id, current_user)
    return jsonify(id=batch.id, kind=batch.kind, status=batch.status, version=batch.version,
                   name=batch.document.name, sha256=batch.document.sha256, error=batch.error,
                   options=batch.options, receipt=batch.receipt, profile_fields=sorted(FIELDS[batch.kind]),
                   rows=[{'id': r.id, 'source': r.source, 'raw': r.raw, 'candidate': r.candidate,
                          'plan': r.plan, 'error': r.error, 'excluded': r.excluded,
                          'allow_update': r.allow_update} for r in batch.rows])


def editable(batch, data):
    if batch.status not in ('needs_review', 'ready') or type(data.get('version')) is not int or data['version'] != batch.version:
        raise Conflict('预览已变化或不能编辑，请刷新')


@agent_bp.patch('/imports/<batch_id>/rows/<int:row_id>')
def update_row(batch_id, row_id):
    batch = owned_batch(batch_id, current_user, lock=True)
    data = payload()
    editable(batch, data)
    row = ImportRow.query.filter_by(id=row_id, batch_id=batch.id).first()
    if not row:
        raise LookupError('行不存在')
    if 'candidate' in data:
        if not isinstance(data['candidate'], dict):
            raise ValueError('候选字段必须是对象')
        row.candidate = data['candidate']
    for flag in ('excluded', 'allow_update'):
        if flag in data:
            if type(data[flag]) is not bool:
                raise ValueError('标记必须为布尔值')
            setattr(row, flag, data[flag])
    revalidate(batch)
    batch.version += 1
    db.session.commit()
    return jsonify(status=batch.status, version=batch.version)


@agent_bp.post('/imports/<batch_id>/validate')
def validate(batch_id):
    batch = owned_batch(batch_id, current_user, lock=True)
    data = payload()
    editable(batch, data)
    if 'options' in data:
        if not isinstance(data['options'], dict):
            raise ValueError('选项必须为对象')
        batch.options = data['options']
    revalidate(batch)
    batch.version += 1
    db.session.commit()
    return jsonify(status=batch.status, version=batch.version)


@agent_bp.post('/imports/<batch_id>/commit')
def commit(batch_id):
    version = payload().get('version')
    if type(version) is not int:
        raise ValueError('需要整数预览版本')
    return jsonify(commit_batch(batch_id, version, current_user))


@agent_bp.post('/imports/<batch_id>/cancel')
def cancel(batch_id):
    batch = owned_batch(batch_id, current_user, lock=True)
    if batch.status in ('committed', 'cancelled'):
        raise Conflict('批次已结束')
    batch.status, batch.lease_token = 'cancelled', None
    db.session.commit()
    return jsonify(status=batch.status)


@agent_bp.post('/imports/<batch_id>/retry')
def retry(batch_id):
    batch = owned_batch(batch_id, current_user, lock=True)
    data = payload()
    if batch.status != 'failed':
        raise Conflict('仅失败批次可重试')
    if not isinstance(data.get('options', batch.options), dict):
        raise ValueError('选项必须为对象')
    batch.options = data.get('options', batch.options)
    batch.status, batch.error, batch.attempts = 'queued', None, 0
    batch.version += 1
    db.session.commit()
    return jsonify(status=batch.status)


@agent_bp.get('/imports/<batch_id>/document')
def original(batch_id):
    batch = owned_batch(batch_id, current_user)
    root = Path(current_app.config['DOCUMENT_FOLDER']).resolve()
    path = (root / batch.document.path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise LookupError('原始文档不存在')
    return send_file(path, as_attachment=True, download_name=batch.document.name)


@agent_bp.get('/agent/changes')
def provenance():
    query = ChangeEvent.query
    if current_user.role != 'admin':
        if not current_user.related_id:
            raise PermissionError('账号没有学号')
        query = query.filter_by(student_id=current_user.related_id)
    sid = request.args.get('student_id')
    if sid:
        query = query.filter_by(student_id=sid)
    events = query.order_by(ChangeEvent.id.desc()).limit(100).all()
    result = []
    for event in events:
        entry = {'id': event.id, 'entity': event.entity, 'entity_id': event.entity_id,
                 'source_type': event.source_type, 'before': event.before, 'after': event.after,
                 'created_at': event.created_at.isoformat()}
        if current_user.role == 'admin':
            entry.update(actor_id=event.actor_id, batch_id=event.batch_id, row_id=event.row_id,
                         draft_id=event.draft_id, reason=event.reason)
        result.append(entry)
    return jsonify(events=result)
