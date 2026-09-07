"""사내톡 공감 — 한 사람당 하나로 정리

대표 지적 (2026-09-07). 말풍선 하나에 같은 사람의 이모지가 계속 쌓였다 —
더블탭으로 ❤️ 를 달아 두고 길게 눌러 😂 를 고르면 둘 다 남았다.

이제부터 쌓이지 않는 것은 서비스가 막는다
(`app/services/reactions.py` `ONE_PER_PERSON` — 다른 것을 고르면 갈아탄다).
**여기서는 이미 쌓여 있던 것을 정리한다** — 안 치우면 예전 메시지에는 그대로
여러 개가 서 있어서, 고쳤는데도 고친 것처럼 안 보인다.

한 사람이 한 메시지에 남긴 것 중 **가장 나중 것만 남긴다** — 마지막에 고른
이모지가 그 사람의 지금 마음이다.

**공지·회의록·프로젝트는 건드리지 않는다.** 거기는 여러 개가 정상이다
(글 하나를 여러 사람이 오래 두고 보는 자리라 ❤️ 와 👍 가 같이 설 수 있다).

되돌리기는 없다 — 지운 줄을 되살릴 방법이 없고, 되살릴 이유도 없다.

Revision ID: rct000000001
Revises: sup000000001
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op

revision: str = "rct000000001"
down_revision: Union[str, Sequence[str], None] = "sup000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # (만든 시각, id) 가 제일 큰 것 하나만 남기고 같은 (메시지·사람) 줄을 지운다.
    # id 까지 보는 것은 같은 초에 두 번 눌린 줄을 가르기 위해서다.
    op.execute(
        """
        DELETE FROM reactions r
        USING reactions keep
        WHERE r.target_type = 'MESSAGE'
          AND keep.target_type = 'MESSAGE'
          AND r.target_id = keep.target_id
          AND r.employee_id = keep.employee_id
          AND (r.created_at, r.id) < (keep.created_at, keep.id)
        """
    )


def downgrade() -> None:
    # 지운 줄은 되살릴 수 없다 (그리고 되살릴 이유도 없다)
    pass
