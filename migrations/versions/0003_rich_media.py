"""Store structured rich text and private, revision-bound images."""
from alembic import op
import sqlalchemy as sa

revision = '0003_rich_media'
down_revision = '0002_posts'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('post_revision', sa.Column('rich_content', sa.JSON(), nullable=True))
    op.create_table('image_asset',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), mysql_engine='InnoDB')
    op.create_index('ix_image_asset_owner_id', 'image_asset', ['owner_id'])
    op.create_table('revision_image',
        sa.Column('revision_id', sa.Integer(), sa.ForeignKey('post_revision.id'), primary_key=True),
        sa.Column('image_id', sa.String(32), sa.ForeignKey('image_asset.id'), primary_key=True),
        mysql_engine='InnoDB')


def downgrade():
    op.drop_table('revision_image')
    op.drop_table('image_asset')
    # Native DROP COLUMN avoids rebuilding post_revision, which post references.
    op.drop_column('post_revision', 'rich_content')
