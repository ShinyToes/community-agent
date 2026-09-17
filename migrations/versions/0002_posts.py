"""Posts with immutable revisions and atomic operation receipts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import MEDIUMTEXT

revision = '0002_posts'
down_revision = '0001_identity'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('post',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('current_revision_id', sa.Integer(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'published', 'hidden', 'deleted')", name='valid_status'),
        mysql_charset='utf8mb4', mysql_engine='InnoDB')
    op.create_index('ix_post_author_id', 'post', ['author_id'])
    op.create_index('ix_post_feed', 'post', ['status', 'published_at', 'id'])
    op.create_table('post_revision',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('post.id'), nullable=False),
        sa.Column('revision_no', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('markdown', sa.Text().with_variant(MEDIUMTEXT(), 'mysql'), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False),
        sa.Column('editor_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('change_reason', sa.String(500), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('post_id', 'revision_no'),
        mysql_charset='utf8mb4', mysql_engine='InnoDB')
    with op.batch_alter_table('post') as batch:
        batch.create_foreign_key('fk_post_current_revision_id_post_revision',
                                 'post_revision', ['current_revision_id'], ['id'])
    op.create_table('tag',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(24), nullable=False),
        sa.UniqueConstraint('name'), mysql_charset='utf8mb4', mysql_collate='utf8mb4_bin', mysql_engine='InnoDB')
    op.create_table('post_tag',
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('post.id'), primary_key=True),
        sa.Column('tag_id', sa.Integer(), sa.ForeignKey('tag.id'), primary_key=True),
        mysql_engine='InnoDB')
    op.create_table('content_chunk',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('revision_id', sa.Integer(), sa.ForeignKey('post_revision.id'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.UniqueConstraint('revision_id', 'position'), mysql_charset='utf8mb4', mysql_engine='InnoDB')
    op.create_table('post_operation',
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('user.id'), primary_key=True),
        sa.Column('key', sa.String(32), primary_key=True),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('post.id'), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), mysql_engine='InnoDB')
    with op.batch_alter_table('audit_event') as batch:
        batch.add_column(sa.Column('post_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('before_version', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('after_version', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_audit_event_post_id_post', 'post', ['post_id'], ['id'])


def downgrade():
    with op.batch_alter_table('audit_event') as batch:
        batch.drop_constraint('fk_audit_event_post_id_post', type_='foreignkey')
        batch.drop_column('post_id')
        batch.drop_column('before_version')
        batch.drop_column('after_version')
    op.drop_table('post_operation')
    op.drop_table('content_chunk')
    op.drop_table('post_tag')
    op.drop_table('tag')
    if op.get_bind().dialect.name == 'sqlite':
        # Avoid recreating a populated table referenced by post_revision on SQLite.
        op.execute(sa.text('UPDATE post SET current_revision_id = NULL'))
    else:
        op.drop_constraint('fk_post_current_revision_id_post_revision', 'post', type_='foreignkey')
    op.drop_table('post_revision')
    op.drop_table('post')
