from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='member')
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (CheckConstraint("role IN ('member', 'admin')", name='valid_role'),)

    @property
    def is_active(self):
        return self.active


class AuthRateBucket(db.Model):
    __tablename__ = 'auth_rate_bucket'
    key = db.Column(db.String(64), primary_key=True)
    window = db.Column(db.BigInteger, primary_key=True)
    count = db.Column(db.Integer, nullable=False)


class AuditEvent(db.Model):
    __tablename__ = 'audit_event'
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(64), nullable=False)
    target_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    before_version = db.Column(db.Integer, nullable=True)
    after_version = db.Column(db.Integer, nullable=True)


class Post(db.Model):
    __tablename__ = 'post'
    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default='draft')
    current_revision_id = db.Column(db.Integer, db.ForeignKey('post_revision.id',
        use_alter=True, name='fk_post_current_revision_id_post_revision'), nullable=True)
    version = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    published_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published', 'hidden', 'deleted')", name='valid_status'),
        db.Index('ix_post_feed', 'status', 'published_at', 'id'),
    )


class PostRevision(db.Model):
    __tablename__ = 'post_revision'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    revision_no = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(120), nullable=False)
    markdown = db.Column(db.Text().with_variant(MEDIUMTEXT(), 'mysql'), nullable=False)
    rich_content = db.Column(db.JSON, nullable=True)
    tags = db.Column(db.JSON, nullable=False)
    editor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    change_reason = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (db.UniqueConstraint('post_id', 'revision_no'),)


class Tag(db.Model):
    __tablename__ = 'tag'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(24), nullable=False, unique=True)
    __table_args__ = {'mysql_collate': 'utf8mb4_bin'}


class PostTag(db.Model):
    __tablename__ = 'post_tag'
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tag.id'), primary_key=True)


class ContentChunk(db.Model):
    __tablename__ = 'content_chunk'
    id = db.Column(db.Integer, primary_key=True)
    revision_id = db.Column(db.Integer, db.ForeignKey('post_revision.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    __table_args__ = (db.UniqueConstraint('revision_id', 'position'),)


class PostOperation(db.Model):
    __tablename__ = 'post_operation'
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    key = db.Column(db.String(32), primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    result = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class ImageAsset(db.Model):
    __tablename__ = 'image_asset'
    id = db.Column(db.String(32), primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    size = db.Column(db.Integer, nullable=False)
    width = db.Column(db.Integer, nullable=False)
    height = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class RevisionImage(db.Model):
    __tablename__ = 'revision_image'
    revision_id = db.Column(db.Integer, db.ForeignKey('post_revision.id'), primary_key=True)
    image_id = db.Column(db.String(32), db.ForeignKey('image_asset.id'), primary_key=True)
