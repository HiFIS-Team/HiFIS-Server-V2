"""document_favorites (문서 즐겨찾기)

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-08-03 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'document_favorites',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('document_id', sa.String(length=36), nullable=False),
        sa.Column('employee_id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id']),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('document_id', 'employee_id', name='uq_document_favorite'),
    )
    op.create_index('ix_document_favorites_document_id', 'document_favorites', ['document_id'])
    op.create_index('ix_document_favorites_employee_id', 'document_favorites', ['employee_id'])


def downgrade() -> None:
    op.drop_index('ix_document_favorites_employee_id', table_name='document_favorites')
    op.drop_index('ix_document_favorites_document_id', table_name='document_favorites')
    op.drop_table('document_favorites')
