from datetime import datetime

from flask import Blueprint, abort, current_app, jsonify, render_template, request
from flask_login import current_user, login_required
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import and_, or_, select

from .extensions import db
from .markdown import render_markdown
from .models import Post, PostRevision, User
from .security import consume_auth_attempt
from .services.posts import mutate, readable, revision_of

bp = Blueprint('posts', __name__)


def actor_id():
    return current_user.id if current_user.is_authenticated else None


def wants_json():
    return request.accept_mimetypes.best == 'application/json'


def serialize(post, revision, username=None):
    return {'id': post.id, 'author_id': post.author_id, 'author': username,
        'status': post.status, 'version': post.version, 'title': revision.title,
        'markdown': revision.markdown, 'tags': revision.tags,
        'published_at': post.published_at.isoformat() if post.published_at else None}


def listing(mine=False):
    signer = URLSafeSerializer(current_app.secret_key, salt='post-list')
    owner = actor_id() if mine else None
    statement = select(Post, PostRevision, User.username).join(
        PostRevision, Post.current_revision_id == PostRevision.id).join(User, Post.author_id == User.id)
    statement = statement.where(Post.deleted_at.is_(None))
    if mine:
        statement = statement.where(Post.author_id == owner, Post.status.in_(['draft', 'published']))
    else:
        statement = statement.where(Post.status == 'published')
    cursor = request.args.get('cursor')
    if cursor:
        try:
            data = signer.loads(cursor)
            if data['owner'] != owner or data['mine'] != mine:
                raise ValueError()
            if mine:
                statement = statement.where(Post.id < int(data['id']))
            else:
                time = datetime.fromisoformat(data['time'])
                statement = statement.where(or_(Post.published_at < time,
                    and_(Post.published_at == time, Post.id < int(data['id']))))
        except (BadSignature, ValueError, TypeError, KeyError):
            abort(400, description='分页链接已失效，请重新打开列表。')
    statement = statement.order_by(Post.id.desc()) if mine else statement.order_by(Post.published_at.desc(), Post.id.desc())
    rows = db.session.execute(statement.limit(21)).all()
    more = len(rows) > 20
    rows = rows[:20]
    next_cursor = None
    if more:
        post = rows[-1][0]
        next_cursor = signer.dumps({'owner': owner, 'mine': mine, 'id': post.id,
                                     'time': post.published_at.isoformat() if post.published_at else None})
    items = [serialize(post, revision, username) for post, revision, username in rows]
    for item in items:
        item['excerpt'] = item.pop('markdown')[:180]
    return items, next_cursor


@bp.get('/posts')
def feed():
    items, cursor = listing()
    if wants_json():
        return jsonify(posts=items, next_cursor=cursor)
    return render_template('index.html', posts=items, next_cursor=cursor)


@bp.get('/me/posts')
@login_required
def mine():
    items, cursor = listing(mine=True)
    if wants_json():
        return jsonify(posts=items, next_cursor=cursor)
    return render_template('my_posts.html', posts=items, next_cursor=cursor)


@bp.get('/posts/new')
@login_required
def new():
    return render_template('editor.html', post=None, revision=None)


@bp.get('/posts/<int:post_id>')
def detail(post_id):
    post = readable(post_id, actor_id())
    revision = revision_of(post)
    author = db.session.get(User, post.author_id)
    if wants_json():
        return jsonify(serialize(post, revision, author.username))
    return render_template('post.html', post=post, revision=revision, author=author,
                            body=render_markdown(revision.markdown))


@bp.get('/posts/<int:post_id>/edit')
@login_required
def edit(post_id):
    post = readable(post_id, actor_id(), owner_only=True)
    return render_template('editor.html', post=post, revision=revision_of(post))


@bp.get('/posts/<int:post_id>/revisions')
@login_required
def revisions(post_id):
    post = readable(post_id, actor_id(), owner_only=True)
    statement = select(PostRevision).where(PostRevision.post_id == post.id)
    before = request.args.get('before', type=int)
    if before:
        statement = statement.where(PostRevision.revision_no < before)
    rows = db.session.scalars(statement.order_by(PostRevision.revision_no.desc()).limit(21)).all()
    more = len(rows) > 20
    rows = rows[:20]
    next_before = rows[-1].revision_no if more else None
    if wants_json():
        return jsonify(revisions=[{'revision_no': r.revision_no, 'title': r.title,
            'markdown': r.markdown, 'tags': r.tags, 'change_reason': r.change_reason,
            'created_at': r.created_at.isoformat()} for r in rows], next_before=next_before)
    return render_template('revisions.html', post=post, revisions=rows,
                            render_markdown=render_markdown, next_before=next_before)


def write(action, post_id=None):
    consume_auth_attempt('post')
    result = mutate(actor_id(), action, request.get_json(), post_id)
    return jsonify(result), (201 if action == 'create' else 200)


@bp.post('/posts')
@login_required
def create():
    return write('create')


@bp.patch('/posts/<int:post_id>')
@login_required
def update(post_id):
    return write('edit', post_id)


@bp.post('/posts/<int:post_id>/publish')
@login_required
def publish(post_id):
    return write('publish', post_id)


@bp.delete('/posts/<int:post_id>')
@login_required
def remove(post_id):
    return write('delete', post_id)


@bp.post('/posts/preview')
@login_required
def preview():
    data = request.get_json()
    value = data.get('markdown') if isinstance(data, dict) else None
    if not isinstance(value, str) or len(value) > 30000:
        abort(400, description='预览正文不能超过 30,000 个字符。')
    return jsonify(html=str(render_markdown(value)))
