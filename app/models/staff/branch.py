"""Branch (지점) 모델 — CLAUDE.md §2.1."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Branch(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "branches"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="BRANCH")  # HQ | BRANCH

    #: 회원 설문 QR 이 담는 값 — `/survey/{survey_token}`.
    #:
    #: **지점 id 를 그대로 쓰지 않는다.** 매장 벽에 붙는 것이라 언젠가 새어 나가는데,
    #: id 면 갈아 끼울 방법이 없다. 토큰이면 새 값을 넣고 QR 만 다시 뽑으면 된다.
    survey_token: Mapped[str | None] = mapped_column(
        String(32), unique=True, index=True, nullable=True
    )
