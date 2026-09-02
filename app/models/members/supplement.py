"""Supplement (영양제) 모델 — 회원 한 사람에게 권한 영양제 한 줄.

운동일지와 달리 **JSONB 로 안 묶는다.** 일지는 한 장을 통째로 열고 통째로
저장하지만, 영양제는 줄 하나가 곧 하나의 권유라 따로 고치고 따로 지운다 —
한 칸에 담으면 줄 하나를 바꾸려고 전체를 다시 써야 한다.

칸 이름은 트레이너가 쓰던 표(노션)를 그대로 옮긴 것이다 —
`영양제 / 얼마나? / 언제? / 왜? / 기억하기`.
"""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Supplement(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "supplements"

    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("members.id"), nullable=False, index=True
    )
    #: 영양제 이름 — "오메가3"
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    #: 얼마나? — "1000~3000mg". 단위가 제각각(mg·IU·캡슐)이라 글로 받는다
    dose: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    #: 언제? — "아침식후"
    timing: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    #: 왜? — "성인병 예방, 염증완화"
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 기억하기 — "마그네슘과 따로 먹기" 처럼 회원이 헷갈리는 지점
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 트레이너가 세운 차례 — 먹는 순서대로 두려고 손으로 옮길 수 있어야 한다
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 적은 트레이너 — 회원은 못 쓰므로 언제나 채워진다
    author_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True, index=True
    )
