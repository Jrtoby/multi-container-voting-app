"""add user.is_admin and index the vote aggregation path

Every schema change made between the original `db.create_all()` boot and the
adoption of migrations lands here, so a volume from before this revision upgrades
cleanly instead of being stamped at head against a stale table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    # Authentication is not authorisation: without this column any registered
    # user can read /admin. Existing users all become standard accounts, which is
    # the safe direction; the first admin is promoted with `flask create-admin`.
    op.add_column(
        'user',
        sa.Column('is_admin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )

    # /results and /admin aggregate votes by (poll_id, choice). Until this exists
    # those are the only two statements that scan the whole vote table.
    op.create_index('ix_vote_poll_choice', 'vote', ['poll_id', 'choice'], unique=False)


def downgrade():
    op.drop_index('ix_vote_poll_choice', table_name='vote')
    op.drop_column('user', 'is_admin')
