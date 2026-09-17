from concurrent.futures import ThreadPoolExecutor
import uuid

from alembic import command
from sqlalchemy import func, select

from community.cli import migration_config
from community.extensions import db
from community.models import AuditEvent, ContentChunk, Post, PostRevision, PostTag, User
from .conftest import login, register, token

JSON = {'Accept': 'application/json'}


def send(client, method, path, data):
    return client.open(path, method=method, json=data,
        headers={**JSON, 'X-CSRFToken': token(client)})


def draft(client, **kwargs):
    data = {'operation_key': uuid.uuid4().hex, 'title': 'Python 学习笔记',
            'markdown': '# 标题\n\n正文示例\n\n```python\nprint(1)\n```', 'tags': ['Python', '笔记']}
    data.update(kwargs)
    return send(client, 'POST', '/posts', data)


def publish(client, post):
    return send(client, 'POST', f"/posts/{post['id']}/publish", {
        'base_version': post['version'], 'operation_key': uuid.uuid4().hex})


def edit(client, post, **kwargs):
    data = {'base_version': post['version'], 'operation_key': uuid.uuid4().hex,
            'title': '更新标题', 'markdown': '新正文', 'tags': ['新标签']}
    data.update(kwargs)
    return send(client, 'PATCH', f"/posts/{post['id']}", data)


def test_draft_private_even_for_admin_and_publication(app, client):
    register(client)
    other = app.test_client(); register(other, 'bob')
    admin = app.test_client(); register(admin, 'admin')
    with app.app_context():
        user = db.session.scalar(select(User).where(User.username == 'admin'))
        user.role = 'admin'; db.session.commit()
    post = draft(client).json
    path = f"/posts/{post['id']}"
    for stranger in [other, admin, app.test_client()]:
        assert stranger.get(path, headers=JSON).status_code == 404
    assert client.get('/posts', headers=JSON).json['posts'] == []
    assert other.get('/me/posts', headers=JSON).json['posts'] == []
    assert len(client.get('/me/posts', headers=JSON).json['posts']) == 1
    assert publish(client, post).status_code == 200
    for stranger in [other, admin, app.test_client()]:
        assert stranger.get(path).status_code == 200
    for stranger in [other, admin]:
        assert stranger.get(path + '/edit').status_code == 404
        assert stranger.get(path + '/revisions', headers=JSON).status_code == 404
        assert edit(stranger, post).status_code == 404
        assert send(stranger, 'DELETE', path, {'base_version': 2, 'operation_key': uuid.uuid4().hex}).status_code == 404
    assert len(app.test_client().get('/posts', headers=JSON).json['posts']) == 1


def test_versions_tags_chunks_and_audit_are_atomic(app, client):
    register(client)
    post = draft(client).json
    post = publish(client, post).json
    response = edit(client, post, change_reason='补充说明')
    assert response.status_code == 200
    assert response.json['version'] == 3 and response.json['status'] == 'published'
    revisions = client.get(f"/posts/{post['id']}/revisions", headers=JSON).json['revisions']
    assert [r['revision_no'] for r in revisions] == [3, 2, 1]
    assert revisions[0]['tags'] == ['新标签']
    assert revisions[-1]['tags'] == ['python', '笔记']
    assert revisions[-1]['title'] == 'Python 学习笔记'
    assert revisions[0]['change_reason'] == '补充说明'
    with app.app_context():
        current = db.session.get(Post, post['id'])
        chunks = db.session.scalars(select(ContentChunk)).all()
        assert chunks and all(c.revision_id == current.current_revision_id for c in chunks)
        assert len(db.session.scalars(select(PostTag)).all()) == 1
        events = db.session.scalars(select(AuditEvent).where(AuditEvent.post_id == post['id']).order_by(AuditEvent.id)).all()
        assert [a.action for a in events] == ['post_create', 'post_publish', 'post_edit']
        assert [(a.before_version, a.after_version) for a in events] == [(0, 1), (1, 2), (2, 3)]


def test_conflict_preserves_current_content(client):
    register(client)
    post = draft(client).json
    assert edit(client, post).status_code == 200
    rejected = edit(client, post, title='过期修改')
    assert rejected.status_code == 409
    current = client.get(f"/posts/{post['id']}", headers=JSON).json
    assert current['version'] == 2 and current['title'] == '更新标题'


def test_idempotent_create_publish_edit_delete_and_key_misuse(app, client):
    register(client)
    key = uuid.uuid4().hex
    first = draft(client, operation_key=key).json
    assert draft(client, operation_key=key).json == first
    assert draft(client, operation_key=key, title='不同请求').status_code == 409
    path = f"/posts/{first['id']}"
    data = {'base_version': 1, 'operation_key': uuid.uuid4().hex}
    published = send(client, 'POST', path + '/publish', data)
    assert send(client, 'POST', path + '/publish', data).json == published.json
    key = uuid.uuid4().hex
    edited = edit(client, published.json, operation_key=key)
    assert edit(client, published.json, operation_key=key).json == edited.json
    data = {'base_version': 3, 'operation_key': uuid.uuid4().hex}
    removed = send(client, 'DELETE', path, data)
    assert send(client, 'DELETE', path, data).json == removed.json
    assert client.get(path).status_code == 404
    assert client.get(path + '/revisions').status_code == 404
    assert client.get('/posts', headers=JSON).json['posts'] == []
    assert client.get('/me/posts', headers=JSON).json['posts'] == []
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(PostRevision)) == 3
        assert db.session.scalar(select(func.count()).select_from(ContentChunk)) == 0
        stored = db.session.get(Post, first['id'])
        assert stored.status == 'deleted' and stored.deleted_at


def test_hidden_cannot_be_edited_republished_or_read(app, client):
    register(client)
    post = publish(client, draft(client).json).json
    with app.app_context():
        db.session.get(Post, post['id']).status = 'hidden'; db.session.commit()
    assert client.get(f"/posts/{post['id']}").status_code == 404
    assert edit(client, post).status_code == 404
    assert publish(client, post).status_code == 404
    assert client.get('/posts', headers=JSON).json['posts'] == []


def test_markdown_preview_and_detail_use_same_safe_renderer(client):
    register(client)
    source = '# 安全标题\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n![x](https://example.com/tracker.png)\n\n**加粗**\n\n| a | b |\n| --- | --- |\n| 1 | 2 |'
    preview = send(client, 'POST', '/posts/preview', {'markdown': source}).json['html']
    assert '<script>' not in preview and 'href="javascript:' not in preview and '<img' not in preview
    assert '<strong>加粗</strong>' in preview and '<table>' in preview
    post = draft(client, markdown=source).json
    assert preview in client.get(f"/posts/{post['id']}").text


def test_invalid_content_csrf_and_disabled_author(app, client):
    assert draft(client).status_code == 401
    register(client)
    for invalid in [{'title': ''}, {'markdown': ''}, {'tags': ['a'] * 6},
                    {'title': 'a' * 121}, {'tags': ['<script>']}, {'author_id': 3}, {'status': 'published'}]:
        assert draft(client, **invalid).status_code == 400
    assert client.post('/posts', json={}).status_code == 400
    post = draft(client).json
    assert edit(client, post, base_version=True).status_code == 400
    assert edit(client, post, base_version=0).status_code == 400
    with app.app_context():
        db.session.scalar(select(User).where(User.username == 'alice')).active = False
        db.session.commit()
    assert edit(client, post).status_code == 401


def test_full_length_chinese_body_and_over_limit(client):
    register(client)
    assert draft(client, markdown='中' * 30000).status_code == 201
    assert draft(client, markdown='中' * 30001).status_code == 400


def test_concurrent_edit_has_one_winner(app, client):
    register(client)
    post = draft(client).json
    clients = [app.test_client(), app.test_client()]
    for c in clients: assert login(c).status_code == 200
    def run(index):
        return edit(clients[index], post, title=f'并发{index}').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, [0, 1])) == [200, 409]
    assert len(client.get(f"/posts/{post['id']}/revisions", headers=JSON).json['revisions']) == 2


def test_concurrent_same_publication_is_one_version(app, client):
    register(client)
    post = draft(client).json
    clients = [app.test_client(), app.test_client()]
    for c in clients: assert login(c).status_code == 200
    data = {'base_version': 1, 'operation_key': uuid.uuid4().hex}
    def run(index):
        return send(clients[index], 'POST', f"/posts/{post['id']}/publish", data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(run, [0, 1]))
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json == responses[1].json
    assert len(client.get(f"/posts/{post['id']}/revisions", headers=JSON).json['revisions']) == 2


def test_rollback_on_indexing_failure(app, client, monkeypatch):
    register(client)
    post = draft(client).json
    from community.services import posts
    def fail(*args): raise RuntimeError('simulated failure')
    monkeypatch.setattr(posts, '_chunks', fail)
    import pytest
    with pytest.raises(RuntimeError):
        publish(client, post)
    current = client.get(f"/posts/{post['id']}", headers=JSON).json
    assert current['status'] == 'draft' and current['version'] == 1
    assert len(client.get(f"/posts/{post['id']}/revisions", headers=JSON).json['revisions']) == 1


def test_feed_cursor_and_rate_limit(app, client):
    register(client)
    for i in range(21):
        assert publish(client, draft(client, title=str(i)).json).status_code == 200
    first = client.get('/posts', headers=JSON).json
    assert len(first['posts']) == 20 and first['next_cursor']
    second = client.get('/posts', query_string={'cursor': first['next_cursor']}, headers=JSON).json
    assert len(second['posts']) == 1
    assert not ({p['id'] for p in first['posts']} & {p['id'] for p in second['posts']})
    assert client.get('/posts?cursor=bad', headers=JSON).status_code == 400
    assert client.get('/me/posts', query_string={'cursor': first['next_cursor']}, headers=JSON).status_code == 400
    app.config['POST_RATE_LIMIT'] = 1
    assert draft(client).status_code == 429


def test_phase0_user_survives_upgrade_and_downgrade(app, client):
    register(client)
    post = draft(client).json
    publish(client, post)
    with app.app_context(), db.engine.begin() as connection:
        command.downgrade(migration_config(connection), '0001_identity')
        command.upgrade(migration_config(connection), 'head')
    assert login(client).status_code == 200
