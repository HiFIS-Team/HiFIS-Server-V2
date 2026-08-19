"""지점 묶음 — branches.share_group · projects/meetings.branch_id

프로젝트·회의록을 **지점 묶음끼리만** 보이게 한다 (2026-08-19 대표 결정).
`첨단`·`화순` 이 한 묶음(`A`), `동광주` 는 단독(`B`) 이다.

**그 전에는 칸막이가 아예 없었다.** `list_projects` 에 필터가 한 줄도 없어서
전 직원이 모든 프로젝트를 봤고, 회의록도 `PEOPLE`(비공개) 만 가렸다.
이 마이그레이션이 그 자리에 처음으로 벽을 세운다.

**`NULL` 은 전 지점**이다 — 본사(HQ)와 이 컬럼이 생기기 전의 행.
대표가 만든 전사 프로젝트가 한 지점에만 안 보이면 안 되기 때문에,
비어 있는 것은 막지 않고 **모두에게 보이는 쪽**으로 뒀다.

백필은 **만든 사람의 지금 지점**으로 한다. 이 값 말고는 근거가 없다.
그 사람이 나중에 지점을 옮겨도 행은 안 따라간다 — 그게 컬럼으로 둔 이유다.

Revision ID: bgrp00000001
Revises: sus000000001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "bgrp00000001"
down_revision: Union[str, None] = "sus000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("share_group", sa.String(length=20), nullable=True))

    for table in ("projects", "meetings"):
        op.add_column(table, sa.Column("branch_id", sa.String(length=36), nullable=True))
        op.create_index(f"ix_{table}_branch_id", table, ["branch_id"])
        op.create_foreign_key(
            f"{table}_branch_id_fkey", table, "branches", ["branch_id"], ["id"]
        )

    # 묶음 값 — 이름으로 찍는다. 지점 id 는 DB 마다 달라서 못 박는다.
    # HQ 는 건드리지 않는다 (NULL = 전 지점).
    op.execute(
        """
        UPDATE branches SET share_group = 'A'
         WHERE type <> 'HQ' AND name IN ('첨단', '화순')
        """
    )
    op.execute(
        """
        UPDATE branches SET share_group = 'B'
         WHERE type <> 'HQ' AND name = '동광주'
        """
    )

    # 백필 — 만든 사람의 지점. 본사 사람이 만든 것은 그대로 두면 안 되고
    # **HQ 지점 id 가 찍힌다.** 조회 쪽에서 share_group 이 NULL 이면
    # 전 지점으로 보므로 결과가 같다.
    op.execute(
        """
        UPDATE projects p SET branch_id = e.branch_id
          FROM employees e WHERE e.id = p.created_by_id
        """
    )
    op.execute(
        """
        UPDATE meetings m SET branch_id = e.branch_id
          FROM employees e WHERE e.id = m.author_id
        """
    )


def downgrade() -> None:
    for table in ("projects", "meetings"):
        op.drop_constraint(f"{table}_branch_id_fkey", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_branch_id", table_name=table)
        op.drop_column(table, "branch_id")
    op.drop_column("branches", "share_group")
