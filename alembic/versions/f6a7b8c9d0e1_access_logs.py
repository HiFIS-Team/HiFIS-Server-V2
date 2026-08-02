"""access_logs

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-31 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'access_logs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('employee_id', sa.String(length=36), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column(
            'event',
            sa.Enum('LOGIN_SUCCESS', 'LOGIN_FAIL', name='accessevent', native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column('ip', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=300), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_access_logs_employee_id', 'access_logs', ['employee_id'])
    op.create_index('ix_access_logs_created_at', 'access_logs', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_access_logs_created_at', table_name='access_logs')
    op.drop_index('ix_access_logs_employee_id', table_name='access_logs')
    op.drop_table('access_logs')
