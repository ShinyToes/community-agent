"""All content writes, permissions and revision transitions live here."""
import hashlib
import json
import re
import unicodedata
import uuid

from flask import abort
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (AuditEvent, ContentChunk, Post, PostOperation, PostRevision,
                      PostTag, Tag, User, ImageAsset, RevisionImage, utcnow)
from ..richtext import compile_document


def content(data, actor_id):
    title, body, tags = data.get('title'), data.get('markdown'), data.get('tags', [])
    rich = data.get('rich_content')
    image_ids = set()
    if rich is not None:
        rich, _, body, image_ids = compile_document(rich)
        found = set(db.session.scalars(select(ImageAsset.id).where(
            ImageAsset.id.in_(image_ids), ImageAsset.owner_id == actor_id)).all()) if image_ids else set()
        if found != image_ids:
            abort(404, description='图片不存在或无权使用。')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
        abort(400, description='标题需要 1–120 个字符。')
    if not isinstance(body, str) or not body.strip() or len(body) > 30000 or '\x00' in body:
        abort(400, description='正文需要 1–30,000 个字符。')
    if not isinstance(tags, list) or len(tags) > 5 or any(not isinstance(t, str) for t in tags):
        abort(400, description='最多添加 5 个标签。')
    names = sorted(set(unicodedata.normalize('NFKC', t).strip().lower() for t in tags))
    if any(not re.fullmatch(r'[\w\-+#.]{1,24}', t) for t in names):
        abort(400, description='标签需为 1–24 位文字、数字或 - + # .，不能包含空格。')
    reason = data.get('change_reason', '')
    if not isinstance(reason, str) or len(reason) > 500:
        abort(400, description='修改说明不能超过 500 个字符。')
    return title.strip(), body, names, reason.strip(), rich, image_ids


def readable(post_id, actor_id=None, *, owner_only=False):
    post = db.session.get(Post, post_id)
    if not post or post.status in ('hidden', 'deleted') or post.deleted_at:
        abort(404)
    if owner_only and post.author_id != actor_id:
        abort(404)
    if post.status != 'published' and post.author_id != actor_id:
        abort(404)
    return post


def revision_of(post):
    revision = db.session.get(PostRevision, post.current_revision_id)
    if not revision or revision.post_id != post.id:
        abort(503)
    return revision


def _tags(post_id, names):
    db.session.execute(delete(PostTag).where(PostTag.post_id == post_id))
    for name in names:
        if db.engine.dialect.name == 'mysql':
            from sqlalchemy.dialects.mysql import insert
            statement = insert(Tag).values(name=name)
            statement = statement.on_duplicate_key_update(name=statement.inserted.name)
        else:
            from sqlalchemy.dialects.sqlite import insert
            statement = insert(Tag).values(name=name).on_conflict_do_nothing(index_elements=['name'])
        db.session.execute(statement)
        tag_id = db.session.scalar(select(Tag.id).where(Tag.name == name))
        db.session.add(PostTag(post_id=post_id, tag_id=tag_id))


def _chunks(post, revision=None):
    ids = select(PostRevision.id).where(PostRevision.post_id == post.id)
    db.session.execute(delete(ContentChunk).where(ContentChunk.revision_id.in_(ids)))
    if revision and post.status == 'published':
        position = 0
        for paragraph in re.split(r'\n\s*\n', revision.markdown):
            for offset in range(0, len(paragraph), 1000):
                piece = paragraph[offset:offset + 1000].strip()
                if piece:
                    db.session.add(ContentChunk(revision_id=revision.id, position=position, text=piece))
                    position += 1


def mutate(actor_id, action, data, post_id=None):
    if not isinstance(data, dict):
        abort(400)
    allowed = {'operation_key', 'base_version'}
    if action in ('create', 'edit'):
        allowed |= {'title', 'markdown', 'tags', 'change_reason', 'rich_content'}
    if set(data) - allowed:
        abort(400, description='请求包含不支持的字段。')
    try:
        key = uuid.UUID(data.get('operation_key', '')).hex
    except (ValueError, TypeError, AttributeError):
        abort(400, description='缺少有效的操作标识，请刷新页面后重试。')
    fingerprint = hashlib.sha256(json.dumps([action, post_id, {k: v for k, v in data.items()
        if k != 'operation_key'}], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    # Serialize account state with disable-user; SQLite is also guarded by CAS below.
    actor = db.session.scalar(select(User).where(User.id == actor_id).with_for_update()
                              .execution_options(populate_existing=True))
    if not actor or not actor.active:
        abort(401)

    def replay():
        previous = db.session.get(PostOperation, (actor_id, key))
        if previous:
            if previous.fingerprint != fingerprint:
                abort(409, description='该操作标识已用于其他内容，请重新提交。')
            return previous.result

    previous = replay()
    if previous:
        return previous
    try:
        if action == 'create':
            values = content(data, actor_id)
            post = Post(author_id=actor_id)
            db.session.add(post)
            db.session.flush()
            before = 0
        else:
            post = readable(post_id, actor_id, owner_only=True)
            before = data.get('base_version')
            if type(before) is not int or before < 1:
                abort(400, description='缺少有效的基础版本。')
            if action == 'publish' and post.status != 'draft':
                abort(409, description='帖子已发布或状态已变化，请重新打开帖子。')
            if action == 'edit':
                if revision_of(post).rich_content and data.get('rich_content') is None:
                    abort(400, description='该帖子包含富文本格式，请在富文本编辑器中修改。')
                values = content(data, actor_id)
            # Claim the exact version before modifying any revision, tag or chunk.
            claimed = db.session.execute(update(Post).where(Post.id == post.id,
                Post.author_id == actor_id, Post.version == before,
                Post.status == post.status, Post.status.in_(['draft', 'published']),
                Post.deleted_at.is_(None)).values(version=before + 1)
                .execution_options(synchronize_session=False))
            if claimed.rowcount != 1:
                db.session.rollback()
                previous = replay()
                if previous:
                    return previous
                abort(409, description='帖子已在其他窗口更新。你的输入已保留，请查看最新版本后再处理。')
            db.session.refresh(post)
        if action == 'create':
            post.version = 1
        if action in ('create', 'edit', 'publish'):
            if action == 'publish':
                old = revision_of(post)
                image_ids = set(db.session.scalars(select(RevisionImage.image_id).where(RevisionImage.revision_id == old.id)))
                values = old.title, old.markdown, old.tags, '发布帖子', old.rich_content, image_ids
                post.status = 'published'
                post.published_at = utcnow()
            title, body, names, reason, rich, image_ids = values
            revision = PostRevision(post_id=post.id, revision_no=post.version,
                title=title, markdown=body, rich_content=rich, tags=names, editor_id=actor_id,
                change_reason=reason or ('创建草稿' if action == 'create' else '保存编辑'))
            db.session.add(revision)
            db.session.flush()
            for image_id in image_ids:
                db.session.add(RevisionImage(revision_id=revision.id, image_id=image_id))
            post.current_revision_id = revision.id
            _tags(post.id, names)
            _chunks(post, revision)
        elif action == 'delete':
            post.status = 'deleted'
            post.deleted_at = utcnow()
            _chunks(post)
        else:
            abort(400)
        db.session.add(AuditEvent(actor_id=actor_id, target_id=actor_id, post_id=post.id,
            action='post_' + action, reason=action, before_version=before, after_version=post.version))
        result = {'id': post.id, 'version': post.version, 'status': post.status}
        db.session.add(PostOperation(actor_id=actor_id, key=key, post_id=post.id,
                                    fingerprint=fingerprint, result=result))
        db.session.commit()
        return result
    except IntegrityError:
        db.session.rollback()
        previous = replay()
        if previous:
            return previous
        abort(409, description='内容保存冲突，请检查最新版本后重试。')
    except Exception:
        db.session.rollback()
        raise
