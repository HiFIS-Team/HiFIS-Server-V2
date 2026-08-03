"""employee_consents / member_consents (동의 이력 §12·§13)

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-08-03 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'employee_consents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('employee_id', sa.String(length=36), nullable=False),
        sa.Column('doc_type', sa.String(length=40), nullable=False),
        sa.Column('doc_version', sa.String(length=40), nullable=False),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('agreed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_employee_consents_employee_id', 'employee_consents', ['employee_id'])

    op.create_table(
        'member_consents',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('member_id', sa.String(length=36), nullable=False),
        sa.Column('doc_type', sa.String(length=40), nullable=False),
        sa.Column('doc_version', sa.String(length=40), nullable=False),
        sa.Column('signature_url', sa.String(length=500), nullable=False),
        sa.Column('collected_by_id', sa.String(length=36), nullable=False),
        sa.Column('agreed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['member_id'], ['members.id']),
        sa.ForeignKeyConstraint(['collected_by_id'], ['employees.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_member_consents_member_id', 'member_consents', ['member_id'])


def downgrade() -> None:
    op.drop_index('ix_member_consents_member_id', table_name='member_consents')
    op.drop_table('member_consents')
    op.drop_index('ix_employee_consents_employee_id', table_name='employee_consents')
    op.drop_table('employee_consents')
