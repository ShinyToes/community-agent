"""Community identity, audit and shared authentication rate limits."""
from alembic import op
import sqlalchemy as sa

revision = '0001_identity'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(32), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(16), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("role IN ('member', 'admin')", name=op.f('ck_user_valid_role')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_user')),
        sa.UniqueConstraint('username', name=op.f('uq_user_username')),
        mysql_charset='utf8mb4', mysql_engine='InnoDB')
    op.create_table('auth_rate_bucket',
        sa.Column('key', sa.String(64), nullable=False),
        sa.Column('window', sa.BigInteger(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('key', 'window', name=op.f('pk_auth_rate_bucket')),
        mysql_charset='utf8mb4', mysql_engine='InnoDB')
    op.create_table('audit_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['user.id'], name=op.f('fk_audit_event_actor_id_user')),
        sa.ForeignKeyConstraint(['target_id'], ['user.id'], name=op.f('fk_audit_event_target_id_user')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_event')),
        mysql_charset='utf8mb4', mysql_engine='InnoDB')


def downgrade():
    op.drop_table('audit_event')
    op.drop_table('auth_rate_bucket')
    op.drop_table('user')
