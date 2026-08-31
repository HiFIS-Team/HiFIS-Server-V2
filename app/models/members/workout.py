"""WorkoutLog (운동일지) 모델 — CLAUDE.md §3.4.

한 표에 PT 와 개인 운동을 같이 담는다([WorkoutKind]). 두 화면이 그리는 것이
**같기 때문**이다 — 웨이트 표, 유산소 표, 자료+피드백. 표를 나누면 같은
코드를 두 벌 쓰게 되고, 한쪽만 고치는 실수가 난다.

표 안의 줄(운동 몇 세트)은 **JSONB 로 담는다.** 줄마다 행을 두면 순서 칸과
조인이 붙는데, 이 값은 일지 하나를 열 때 통째로 읽고 통째로 쓴다 —
따로 검색하거나 집계할 일이 없다(사내톡 첨부·회의록 블록과 같은 판단).
"""

from datetime import date

from sqlalchemy import Date, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.enums import WorkoutKind


class WorkoutLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workout_logs"

    member_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("members.id"), nullable=False, index=True
    )
    kind: Mapped[WorkoutKind] = mapped_column(
        SAEnum(WorkoutKind, native_enum=False, length=20), nullable=False, index=True
    )
    #: 몇 회차인가 — PT 만 붙는다. 회원이 결제한 회차를 넘길 수 없고 한 회차에 하나뿐이다
    session_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 그날 뭘 했나 — "가슴, 삼두" 처럼 부위를 적는다. 목록에 이 값이 제목으로 뜬다
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    #: 수업한 날 — 적은 날이 아니다. 밀린 일지를 나중에 채워 넣는 일이 잦다
    performed_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: 쓴 사람(트레이너) — **비어 있으면 회원이 공개 주소에서 직접 쓴 것**이다
    author_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=True, index=True
    )
    #: 웨이트 표 — [{"part","name","load","sets"}, ...] (무게/횟수는 "60kg x 12" 처럼 한 칸)
    weights: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: 유산소 표 — [{"name","duration"}, ...]
    cardio: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: 자료 묶음 — [{"items":[{"url","kind"}...], "feedback": "..."}, ...]
    #:
    #: **묶음이다.** 영상 하나 올리고 그 밑에 한마디, 다시 사진 셋 올리고 또
    #: 한마디를 쓰는 식이라 자료와 피드백이 한 덩어리로 붙어 다닌다.
    media: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: 개인 운동에 트레이너가 다는 총평 — PT 는 묶음마다 쓰므로 대개 비어 있다
    trainer_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
