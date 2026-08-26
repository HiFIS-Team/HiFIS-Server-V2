"""출퇴근 단말 생존 신호 — scan_terminals 에 started_at·heartbeat_at·scanner_at·scanner_port·alerted_at

화순에서 "바코드가 안 된다"는 말이 왔는데 **서버 쪽에 아무 흔적이 없었다**
(2026-08-26). 성공도 실패도 없이 요청 자체가 안 왔다 — 카운터 PC 의 프로그램이
안 돌면 읽은 값이 PC 밖으로 못 나가기 때문이다.

제일 나쁜 건 **스캐너 부저가 그때도 삑 소리를 낸다**는 것이다. 찍은 사람은
됐다고 믿고, 저녁이 되면 결근 알림이 나가서 **안 나온 사람처럼 보인다.**

`last_used_at` 하나로는 "아무도 안 찍었다"와 "찍었는데 안 왔다"를 못 가른다.
그래서 프로그램이 **자기가 살아 있다고 따로 말하게** 한다.

    started_at    프로그램이 마지막으로 시작한 시각 — 사고 시각보다 뒤면 그때는 안 떠 있던 것이다
    heartbeat_at  마지막 생존 신호 (5분마다)
    scanner_at    스캐너 포트를 마지막으로 붙잡은 시각
    scanner_port  지금 붙은 포트 — **null 이면 스캐너를 못 찾는 중이다**
    alerted_at    침묵 알림을 마지막으로 보낸 시각 (하루 한 번으로 묶는 데 쓴다)

**`last_used_at` 은 손대지 않는다.** 그 값은 여전히 "사람이 찍은 시각"만
뜻해야 한다 — 하트비트가 같이 밀면 아무도 안 찍은 날에도 방금 찍은 것처럼
보여서, 가르려고 만든 기능이 뜻을 잃는다.

Revision ID: sct000000001
Revises: hsn000000002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sct000000001"
down_revision: Union[str, Sequence[str], None] = "hsn000000002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 전부 nullable — 이미 깔린 옛 스크립트는 이 신호를 안 보낸다.
    # null 은 "모른다"지 "꺼져 있다"가 아니라서, 감시 잡이 그 둘을 갈라 읽는다.
    op.add_column("scan_terminals", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scan_terminals", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scan_terminals", sa.Column("scanner_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scan_terminals", sa.Column("scanner_port", sa.String(20), nullable=True))
    op.add_column("scan_terminals", sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("scan_terminals", "alerted_at")
    op.drop_column("scan_terminals", "scanner_port")
    op.drop_column("scan_terminals", "scanner_at")
    op.drop_column("scan_terminals", "heartbeat_at")
    op.drop_column("scan_terminals", "started_at")
