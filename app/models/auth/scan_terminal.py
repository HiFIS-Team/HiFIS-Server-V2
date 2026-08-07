"""ScanTerminal (지점 출퇴근 단말) 모델 — 사람이 아닌 기기의 자격증명.

지점 카운터 PC 에 꽂힌 바코드 스캐너가 쓴다. 그 PC 는 **회원 등록 등 다른
일에도 같이 쓰는 공용 컴퓨터**라 사람 계정으로 HiFIS 를 켜 두면 곤란하다 —
누구나 그 화면에서 급여·사내톡·조직도를 들여다볼 수 있고, MASTER 로 켜 두면
모니터링(남의 접속·활동·대화)까지 열린다.

그래서 **화면 없이 포트만 듣는 프로그램**이 돌고, 그 프로그램은 이 토큰으로
`POST /attendance/scan` **하나만** 부를 수 있다. 토큰이 그 PC 에서 새어도
할 수 있는 일이 출퇴근 찍기뿐이다.

- 토큰 원문은 **저장하지 않는다** (sha256 만 남긴다). 발급 직후 한 번만 보여준다.
- 만료가 없다. 카운터에 붙여 두고 계속 쓰는 것이라 만료를 두면 어느 날 아침
  갑자기 출퇴근이 안 찍힌다. 대신 언제든 폐기할 수 있다.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class ScanTerminal(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "scan_terminals"

    #: 이 단말이 놓인 지점 — **찍을 수 있는 범위가 이걸로 정해진다.**
    #: 화순점 단말로는 화순 직원만 찍힌다 (사람 계정의 지점 검사와 같은 규칙).
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id"), nullable=False, index=True
    )

    #: 사람이 알아볼 이름 — `화순점 카운터` 처럼. 여러 대가 되면 구분해야 한다.
    name: Mapped[str] = mapped_column(String(50), nullable=False)

    #: 토큰의 sha256(hex). **원문은 어디에도 안 남는다** — 잃어버리면 새로 발급한다.
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )

    issued_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )

    #: 폐기 시각 — 채워지면 그 토큰은 더 이상 안 통한다 (행은 남겨서 이력을 본다)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: 마지막으로 스캔을 보낸 시각 — **살아 있는지 보는 유일한 단서다.**
    #: 카운터 PC 가 꺼져 있거나 프로그램이 죽었으면 여기가 안 갱신된다.
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
