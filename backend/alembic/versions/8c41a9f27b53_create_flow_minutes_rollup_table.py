"""create flow_minutes rollup table

Revision ID: 8c41a9f27b53
Revises: 305200e81008
Create Date: 2026-09-12 01:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c41a9f27b53'
down_revision: Union[str, None] = '305200e81008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'flow_minutes',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('bucket', sa.DateTime(timezone=True), nullable=False),
        sa.Column('bytes', sa.BigInteger(), nullable=False),
        sa.Column('packets', sa.BigInteger(), nullable=False),
        sa.Column('flow_count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_id', 'bucket', name='uq_flow_minutes_device_bucket'),
    )
    op.create_index(
        'ix_flow_minutes_bucket_device', 'flow_minutes', ['bucket', 'device_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_flow_minutes_bucket_device', table_name='flow_minutes')
    op.drop_table('flow_minutes')
