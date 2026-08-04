"""projects.owner_id — 맡은 사람(만든 사람과 다를 수 있다)

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-08-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'e9f0a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('owner_id', sa.String(length=36), nullable=True))
    op.create_index('ix_projects_owner_id', 'projects', ['owner_id'])
    op.create_foreign_key(
        'projects_owner_id_fkey', 'projects', 'employees', ['owner_id'], ['id']
    )
    # 이미 쌓인 프로젝트는 만든 사람이 담당이었다 — 그대로 채운다
    op.execute('UPDATE projects SET owner_id = created_by_id WHERE owner_id IS NULL')


def downgrade() -> None:
    op.drop_constraint('projects_owner_id_fkey', 'projects', type_='foreignkey')
    op.drop_index('ix_projects_owner_id', table_name='projects')
    op.drop_column('projects', 'owner_id')
