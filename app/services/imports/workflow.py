from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import uuid

from flask import current_app
from sqlalchemy import or_

from app.extensions import db
from app.agent_models import Document, ImportBatch, ImportRow, ChangeEvent
from app.models import User
from app.services.imports.parsers import parse_document
from app.services.imports.profiles import FIELDS, plan_row, apply_plan, snapshot
from app.utils.audit import set_audit_user


class Conflict(ValueError):
    pass


def require_admin(actor):
    if not actor or not actor.is_active or actor.role != 'admin':
        raise PermissionError('仅管理员可执行此操作')


def owned_batch(batch_id, actor, *, lock=False):
    require_admin(actor)
    query = ImportBatch.query.filter_by(id=batch_id, owner_id=actor.user_id)
    batch = (query.with_for_update().populate_existing() if lock else query).first()
    if batch is None:
        raise LookupError('导入批次不存在')
    return batch


def create_batch(upload, kind, options, actor):
    require_admin(actor)
    if kind not in FIELDS:
        raise ValueError('请选择导入业务类型')
    suffix = Path(upload.filename or '').suffix.lower()
    if suffix not in ('.csv', '.xlsx', '.pdf', '.png', '.jpg', '.jpeg', '.docx'):
        raise ValueError('支持 CSV、XLSX、PDF、图片、DOCX')
    content = upload.stream.read(16 * 1024 * 1024 + 1)
    if not content or len(content) > 16 * 1024 * 1024:
        raise ValueError('文件为空或超过16MB')
    root = Path(current_app.config['DOCUMENT_FOLDER']).resolve()
    root.mkdir(parents=True, exist_ok=True)
    filename = uuid.uuid4().hex + suffix
    path = root / filename
    path.write_bytes(content)
    document = Document(owner_id=actor.user_id, name=Path(upload.filename).name[:255],
        path=filename, sha256=hashlib.sha256(content).hexdigest(), size=len(content))
    try:
        db.session.add(document)
        db.session.flush()
        batch = ImportBatch(document_id=document.id, owner_id=actor.user_id, kind=kind, options=options)
        db.session.add(batch)
        db.session.commit()
        return batch
    except Exception:
        db.session.rollback()
        path.unlink(missing_ok=True)
        raise


def revalidate(batch):
    seen = set()
    for row in batch.rows:
        row.error = None
        row.plan = None
        if row.excluded:
            continue
        try:
            row.plan = plan_row(batch.kind, row.candidate, batch.options, allow_update=row.allow_update)
            key = row.plan['key']
            if key in seen:
                raise ValueError('文件内存在重复目标，请明确排除重复行')
            seen.add(key)
            if row.plan['action'] == 'update' and not row.allow_update:
                raise ValueError('已有记录将被修改；请核对差异并勾选允许更新')
        except (ValueError, TypeError, OverflowError) as error:
            row.error = str(error)
    selected = [r for r in batch.rows if not r.excluded]
    batch.status = 'ready' if selected and all(r.plan and not r.error for r in selected) else 'needs_review'


def run_one():
    """Lease acquisition via compare-and-swap; parsing never holds a DB transaction."""
    now = datetime.utcnow()
    ImportBatch.query.filter(ImportBatch.status == 'parsing', ImportBatch.lease_until < now,
                             ImportBatch.attempts >= 3).update(
        {'status': 'failed', 'error': '任务多次中断，请检查 Worker 后显式重试',
         'lease_token': None, 'lease_until': None}, synchronize_session=False)
    db.session.commit()
    batch = ImportBatch.query.filter(or_(
        ImportBatch.status == 'queued',
        (ImportBatch.status == 'parsing') & (ImportBatch.lease_until < now),
    ), ImportBatch.attempts < 3).order_by(ImportBatch.created_at).first()
    if not batch:
        db.session.rollback()
        return False
    bid, previous, token = batch.id, batch.status, uuid.uuid4().hex
    query = ImportBatch.query.filter_by(id=bid, status=previous)
    if previous == 'parsing':
        query = query.filter(ImportBatch.lease_until < now)
    updated = query.update({'status': 'parsing', 'lease_token': token,
        'lease_until': now + timedelta(minutes=20), 'attempts': ImportBatch.attempts + 1},
        synchronize_session=False)
    db.session.commit()
    if not updated:
        return True
    batch = db.session.get(ImportBatch, bid)
    root = Path(current_app.config['DOCUMENT_FOLDER']).resolve()
    path = (root / batch.document.path).resolve()
    if not path.is_relative_to(root):
        raise ValueError('文档存储路径非法')
    kind, options = batch.kind, dict(batch.options)
    db.session.rollback()
    def heartbeat():
        changed = ImportBatch.query.filter_by(id=bid, status='parsing', lease_token=token).update(
            {'lease_until': datetime.utcnow() + timedelta(minutes=20)}, synchronize_session=False)
        db.session.commit()
        if not changed:
            raise ValueError('任务已取消或租约失效')
    try:
        records = parse_document(path, kind, options, heartbeat=heartbeat)
        error = None
    except Exception as exc:
        records = []
        error = (str(exc) if isinstance(exc, ValueError) else '') or '文档解析失败，请检查格式或配置后重试'
        current_app.logger.warning('Document parsing failed (%s)', type(exc).__name__)
    # Stale workers and cancelled batches cannot publish results.
    batch = ImportBatch.query.filter_by(id=bid, status='parsing', lease_token=token).with_for_update().populate_existing().first()
    if not batch or batch.lease_until < datetime.utcnow():
        db.session.rollback()
        return True
    actor = db.session.get(User, batch.owner_id)
    if not actor or not actor.is_active or actor.role != 'admin':
        error = '操作者权限已失效'
    batch.lease_until = None
    batch.lease_token = None
    batch.error = error
    if error:
        batch.status = 'failed'
    else:
        for row in list(batch.rows):
            db.session.delete(row)
        db.session.flush()
        batch.rows = [ImportRow(position=i, source=r['source'], raw=r['raw'], candidate=r['candidate'])
                      for i, r in enumerate(records, 1)]
        revalidate(batch)
        batch.version += 1
    db.session.commit()
    return True


def commit_batch(batch_id, version, actor):
    batch = owned_batch(batch_id, actor, lock=True)
    if batch.status == 'committed':
        if batch.receipt['version'] != version:
            raise Conflict('确认版本不一致')
        return batch.receipt
    if batch.status != 'ready' or batch.version != version:
        raise Conflict('批次状态或预览版本已变化，请重新预览')
    selected = [r for r in batch.rows if not r.excluded]
    if not selected:
        raise ValueError('没有选中的有效行')
    # Deterministic order for business locks across concurrent imports.
    fresh = []
    for row in sorted(selected, key=lambda r: (str(r.candidate.get('offering_id', batch.options.get('offering_id', ''))),
                                                str(r.candidate.get('student_id', '')), str(r.plan['key']))):
        if row.error or not row.plan:
            raise Conflict('批次含有未处理错误')
        current = plan_row(batch.kind, row.candidate, batch.options, lock=True, allow_update=row.allow_update)
        if current != row.plan:
            raise Conflict('数据库或计算规则已变化，请重新校验后确认')
        if current['action'] == 'update' and not row.allow_update:
            raise Conflict('未确认覆盖已有记录')
        fresh.append((row, current))
    set_audit_user()
    counts = {'insert': 0, 'update': 0, 'unchanged': 0, 'excluded': sum(r.excluded for r in batch.rows)}
    for row, plan in fresh:
        record = apply_plan(plan)
        db.session.flush()
        counts[plan['action']] += 1
        if plan['action'] != 'unchanged':
            db.session.add(ChangeEvent(actor_id=actor.user_id, source_type='document',
                batch_id=batch.id, row_id=row.id, entity=record.__tablename__,
                entity_id=str(getattr(record, list(record.__table__.primary_key.columns)[0].name)),
                student_id=plan['student_id'], before=plan['before'], after=snapshot(record)))
    batch.status = 'committed'
    batch.receipt = {'batch_id': batch.id, 'version': version, 'counts': counts,
                     'committed_at': datetime.utcnow().isoformat()}
    db.session.commit()
    return batch.receipt
