"""지점 QR 출퇴근 — QR 시크릿과 허용 IP

대표 결정 (2026-08-28). 카운터 PC·스캐너를 없애고 **직원 폰이 매장에 붙은
QR 을 찍는다.** 기계가 없어지니 절전·부팅·업데이트로 멈출 자리가 사라진다.

**고정 QR 이라 사진을 찍어 두면 집에서도 찍힌다.** 그래서 서버가 요청이
**그 지점 인터넷에서 왔는지**를 같이 본다 (`allowed_ips`).

- `scan_secret` — QR 에 담기는 값. 지점 id 만 담으면 아는 사람이 QR 을
  지어낼 수 있어서 한 겹 더 둔다. 새면 새 QR 을 뽑아 붙이면 된다.
- `allowed_ips` — 그 지점 인터넷의 공인 IP 들. 대표가 지점에서 버튼 한 번
  누르면 등록된다. 회선이 동적이라 바뀌면 다시 누른다.

**주차장에서 찍히는 것까지는 안 막는다** (2026-08-28 대표 결정). 그걸 막으려면
30초마다 바뀌는 QR 이 필요하고, 그러면 카운터에 화면을 둬야 해서 기계를
없애는 뜻이 사라진다.

Revision ID: qrs000000001
Revises: sct000000001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "qrs000000001"
down_revision: Union[str, Sequence[str], None] = "sct000000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("scan_secret", sa.String(32), nullable=True))
    op.add_column(
        "branches",
        sa.Column("allowed_ips", sa.JSON(), nullable=False, server_default="[]"),
    )
    # 지점마다 시크릿을 심는다 — 없으면 QR 을 못 만든다
    op.execute(
        "UPDATE branches SET scan_secret = replace(gen_random_uuid()::text, '-', '') "
        "WHERE scan_secret IS NULL"
    )


def downgrade() -> None:
    op.drop_column("branches", "allowed_ips")
    op.drop_column("branches", "scan_secret")
