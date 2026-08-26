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

    # ------------------------------------------------------------------
    # 생존 신호 (2026-08-26) — `last_used_at` 만으로는 못 가르는 것을 가른다
    #
    # 화순에서 스캔이 통째로 안 들어온 날, 서버에는 성공도 실패도 없었다.
    # 요청이 안 온 것이라 **아무도 안 찍은 것과 구별이 안 됐다.** 그래서
    # 프로그램이 자기가 살아 있다고 따로 말하게 했다.
    #
    # **이 값들은 `last_used_at` 을 건드리지 않는다.** 저 값은 계속
    # "사람이 찍은 시각"만 뜻해야 한다 — 하트비트가 같이 밀면 아무도 안 찍은
    # 날에도 방금 찍은 것처럼 보여서 가르려던 뜻이 사라진다.
    # ------------------------------------------------------------------

    #: 프로그램이 마지막으로 시작한 시각. **사고 시각보다 뒤면 그때는 안 떠 있던 것이다.**
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: 마지막 생존 신호(5분마다). 여기가 멎으면 PC 가 꺼졌거나 프로그램이 죽은 것이다.
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: 스캐너 포트를 마지막으로 붙잡은 시각.
    scanner_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: 지금 붙어 있는 포트(`COM3`). **null 이면 스캐너를 못 찾는 중이다** —
    #: 프로그램은 도는데 케이블이 빠졌거나 드라이버가 안 잡힌 상태다.
    scanner_port: Mapped[str | None] = mapped_column(String(20), nullable=True)

    #: 침묵 알림을 마지막으로 보낸 시각 — **하루 한 번**으로 묶는 데만 쓴다.
    #: 알림 원장으로 세면 단말별로 못 가른다(같은 종류가 지점 수만큼 쌓인다).
    alerted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
