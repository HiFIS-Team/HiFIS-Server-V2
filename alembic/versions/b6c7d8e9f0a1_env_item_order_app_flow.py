"""환경정비 항목 순서를 앱이 쓰던 흐름으로 (env_items.sort_order)

**앱이 정한 차례다** — 칩을 위에서 아래로 훑으며 누르게 돼 있어서
실제 일하는 차례와 다르면 손이 왔다 갔다 한다.

`b0c1d2e3f4a5` 에서 흐름별로 묶긴 했는데 묶음 **안쪽** 차례가 달랐다.
빨래가 `빨래정리 → 건조기 → 세탁` 으로 거꾸로 섰고(돌리기 전에 개는 꼴),
화장실청소가 청소 앞쪽으로, 클레임해결이 회원 묶음으로 갔다.

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-08-04 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6c7d8e9f0a1'
down_revision: Union[str, Sequence[str], None] = 'a5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# app/api/scoring/env.py 의 BASE_ENV_ITEMS 와 **같은 차례**여야 한다
ORDER = [
    "세탁", "건조기", "빨래정리",
    "구역청소", "복도청소", "락커정리",
    "남탈부스", "남탈청소", "여탈부스", "여탈청소", "화장실청소",
    "기구관리", "회원지도", "TM회원관리",
    "게시물", "스토리", "전단지", "현수막", "족자", "블로그",
    "클레임해결", "기타",
]

# 되돌릴 때 쓰는 b0c1d2e3f4a5 의 차례
PREVIOUS = [
    "빨래정리", "건조기", "세탁",
    "구역청소", "복도청소", "화장실청소", "락커정리",
    "남탈부스", "남탈청소", "여탈부스", "여탈청소",
    "기구관리", "회원지도", "TM회원관리", "클레임해결",
    "현수막", "족자", "전단지", "블로그", "게시물", "스토리",
    "기타",
]


def _apply(names: list[str]) -> None:
    """이름으로 번호를 다시 매긴다 — 지점마다 같은 이름이 하나씩 있다.

    목록에 없는 이름(지점이 새로 만든 항목)은 건드리지 않는다.
    그대로 두면 번호가 커서 자연히 맨 뒤에 선다.
    """
    for order, name in enumerate(names):
        op.execute(
            sa.text("UPDATE env_items SET sort_order = :o WHERE name = :n").bindparams(
                o=order, n=name
            )
        )


def upgrade() -> None:
    _apply(ORDER)


def downgrade() -> None:
    _apply(PREVIOUS)
