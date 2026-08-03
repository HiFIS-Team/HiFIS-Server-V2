"""project_activities 타임라인 + projects.color

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-08-03 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('color', sa.String(length=20), nullable=True))
    op.create_table(
        'project_activities',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.String(length=36), nullable=False),
        sa.Column('actor_id', sa.String(length=36), nullable=True),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.ForeignKeyConstraint(['actor_id'], ['employees.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_project_activities_project_id', 'project_activities', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_project_activities_project_id', table_name='project_activities')
    op.drop_table('project_activities')
    op.drop_column('projects', 'color')
