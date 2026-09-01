"""달마다 도는 추첨 — 매장 TV 가 게임으로 굴려 보여준다 (2026-09-01 대표 요청).

전달에 친절도 설문을 낸 회원이 **다음 달 추첨 대상**이다 (8월 설문 → 9월 추첨).
지점마다 따로 뽑는다 — TV 가 지점마다 하나고, 설문의 지점도 **칭찬받은 직원의
소속**으로 가른다 (`api/public/tv.py` 와 같은 규칙).

## 왜 참가자를 통째로 베껴 두나 (`entries`)

설문은 지워질 수 있다. 그때 참가자 명단을 설문에서 다시 만들면 **지난 추첨의
화면이 달라진다** — 칸이 하나 사라지고 공이 다른 데로 떨어진다. 뽑은 순간의
명단을 그대로 박아 두면 몇 달 뒤에 틀어도 똑같다.

## 왜 시드를 따로 두나 (`seed`)

**당첨자는 시드가 정하지 않는다.** 당첨은 `secrets` 로 안전하게 뽑아 이 행에
박고, 시드는 **화면이 굴러가는 모양**(공이 어디서 떨어지고 어느 범퍼를 맞는지)만
정한다. 그래서 TV 를 껐다 켜도 같은 공이 같은 길로 굴러 같은 사람에게 떨어진다.

물리로 당첨자를 정하면 안 된다 — 프레임이 한 번 밀리면 다른 사람이 되고,
"왜 저 사람이냐"에 답할 근거도 안 남는다.
"""

from sqlalchemy import Enum as SAEnum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import DrawGame


class Draw(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "draws"
    __table_args__ = (
        # 지점·달에 하나뿐이다 — 잡이 두 번 돌아도 두 번 뽑히지 않는다
        UniqueConstraint("branch_id", "period", name="uq_draws_branch_period"),
    )

    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=False, index=True
    )

    #: 이벤트가 열리는 달 `YYYY-MM` — 대상은 **그 전달** 설문이다
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)

    game: Mapped[DrawGame] = mapped_column(
        SAEnum(DrawGame, native_enum=False, length=16), nullable=False
    )

    #: 화면이 굴러가는 모양을 정하는 값 — **당첨자는 이걸로 안 뽑는다**
    seed: Mapped[str] = mapped_column(String(32), nullable=False)

    #: 뽑은 순간의 참가자 — `[{"id", "name", "phone"}]`
    #:
    #: 설문이 나중에 지워져도 화면이 안 바뀌게 통째로 베껴 둔다.
    #: 같은 사람이 여러 번 냈어도 **한 줄이다** (이름·전화로 묶는다).
    entries: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    #: 당첨자들이 [entries] 의 몇 번째인가 — **세 명이다** (2026-09-01 대표 결정).
    #:
    #: 참가자가 셋보다 적으면 그만큼만 들어가고, 한 명도 없으면 빈 배열이다.
    #: 순서가 곧 게임의 1·2·3등 자리다 — 화면이 그 차례로 붙인다.
    winner_indexes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
