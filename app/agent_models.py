"""Additive Agent tables. Business records remain in app.models."""
from datetime import datetime
import uuid
from app.extensions import db


def identifier():
    return uuid.uuid4().hex


class Document(db.Model):
    __tablename__ = 'agent_document'
    id = db.Column(db.String(32), primary_key=True, default=identifier)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    path = db.Column(db.String(255), nullable=False)
    sha256 = db.Column(db.String(64), nullable=False, index=True)
    size = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ImportBatch(db.Model):
    __tablename__ = 'agent_import_batch'
    id = db.Column(db.String(32), primary_key=True, default=identifier)
    document_id = db.Column(db.String(32), db.ForeignKey('agent_document.id'), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    options = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(24), nullable=False, default='queued', index=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    error = db.Column(db.Text)
    lease_token = db.Column(db.String(32))
    lease_until = db.Column(db.DateTime)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    receipt = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    document = db.relationship(Document)
    rows = db.relationship('ImportRow', cascade='all, delete-orphan', order_by='ImportRow.position')


class ImportRow(db.Model):
    __tablename__ = 'agent_import_row'
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(32), db.ForeignKey('agent_import_batch.id'), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)
    source = db.Column(db.JSON, nullable=False)
    raw = db.Column(db.JSON, nullable=False)
    candidate = db.Column(db.JSON, nullable=False)
    plan = db.Column(db.JSON)
    error = db.Column(db.Text)
    excluded = db.Column(db.Boolean, default=False, nullable=False)
    allow_update = db.Column(db.Boolean, default=False, nullable=False)
    __table_args__ = (db.UniqueConstraint('batch_id', 'position'),)


class Conversation(db.Model):
    __tablename__ = 'agent_conversation'
    id = db.Column(db.String(32), primary_key=True, default=identifier)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    role_scope = db.Column(db.String(20), nullable=False)
    subject_scope = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AgentMessage(db.Model):
    __tablename__ = 'agent_message'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.String(32), db.ForeignKey('agent_conversation.id'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    result = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ChangeDraft(db.Model):
    __tablename__ = 'agent_change_draft'
    id = db.Column(db.String(32), primary_key=True, default=identifier)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    conversation_id = db.Column(db.String(32), db.ForeignKey('agent_conversation.id'), nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    candidate = db.Column(db.JSON, nullable=False)
    options = db.Column(db.JSON, nullable=False)
    plan = db.Column(db.JSON, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')
    receipt = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ChangeEvent(db.Model):
    __tablename__ = 'agent_change_event'
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.user_id'), nullable=False)
    source_type = db.Column(db.String(20), nullable=False)
    batch_id = db.Column(db.String(32), db.ForeignKey('agent_import_batch.id'))
    row_id = db.Column(db.Integer, db.ForeignKey('agent_import_row.id'))
    draft_id = db.Column(db.String(32), db.ForeignKey('agent_change_draft.id'))
    entity = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.String(50), nullable=False)
    student_id = db.Column(db.String(20), index=True)
    before = db.Column(db.JSON, nullable=False)
    after = db.Column(db.JSON, nullable=False)
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
