"""컴플레인을 매장 TV 에서만 빼는 칸

Revision ID: tvh000000001
Revises: sgs000000001
Create Date: 2026-09-16

해결은 해결인데 **벽에 걸 글이 아닌** 컴플레인이 있다. 사람이나 무리를
지목하는 것이 그렇다 — 회원이 보는 벽에 다른 회원 이야기를 거는 셈이다.

예전에는 `resolved_at` 을 비워서 뺐는데, 그건 '해결 시각이 없다' 라고 적는
것이라 뜻이 어긋났다. 앞으로 그 값을 쓰는 화면이 생기면 그 한 건만 빈칸이 된다.

**TV 조회에서만 뺀다** — 해결 완료·점수·문자·앱 기록은 그대로 간다.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "tvh000000001"
down_revision: Union[str, Sequence[str], None] = "sgs000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kindness_surveys",
        sa.Column(
            "tv_hidden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # 손으로 빼 뒀던 한 건을 제자리로 돌린다 — `resolved_at` 을 비워서 TV 에서
    # 뺐던 화순 09-15 건이다 (`.claude/backend-gap.md` 87번). 이제 칸이 있으니
    # 해결 시각을 되돌리고 이 칸으로 뺀다.
    op.execute(
        """
        UPDATE kindness_surveys
           SET tv_hidden = true,
               resolved_at = COALESCE(resolved_at, done_requested_at)
         WHERE improvement_status = 'DONE'
           AND resolved_at IS NULL
           AND done_requested_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("kindness_surveys", "tv_hidden")
