"""leave_request.half_period (반차 오전/오후)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-31 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'leave_requests',
        sa.Column(
            'half_period',
            sa.Enum('AM', 'PM', name='halfperiod', native_enum=False, length=10),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('leave_requests', 'half_period')
