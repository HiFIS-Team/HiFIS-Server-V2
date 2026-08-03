"""project_todos 체크리스트 + projects.start_at

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-03 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('start_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        'project_todos',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.String(length=36), nullable=False),
        sa.Column('content', sa.String(length=300), nullable=False),
        sa.Column('assignee_id', sa.String(length=36), nullable=True),
        sa.Column('done', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('sort', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by_id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['assignee_id'], ['employees.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['employees.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_project_todos_project_id', 'project_todos', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_project_todos_project_id', table_name='project_todos')
    op.drop_table('project_todos')
    op.drop_column('projects', 'start_at')
