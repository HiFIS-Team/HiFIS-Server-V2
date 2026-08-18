"""앱 사용 기록 — **어느 화면을 열었고 무엇을 봤는지** (2026-08-18).

세 로그가 각자 다른 것을 남긴다. 이 표는 셋 중 마지막 자리를 채운다.

| | 무엇을 남기나 | 어디서 |
|---|---|---|
| `access_logs` | 들어왔다 / 못 들어왔다 | 로그인 |
| `audit_logs` | **한 일** (등록·수정·삭제) | 쓰기 요청 미들웨어 |
| **`app_trails`** | **본 것** (화면 이동·열람) | **앱이 직접 보낸다** |

**왜 앱이 보내나** — 화면을 옮기는 것은 서버를 안 거친다. 탭을 눌러 옮기거나
이미 받아 둔 목록을 훑는 동안 요청이 한 건도 안 나간다. 그래서 서버 쪽
미들웨어로는 잡을 방법이 없고 앱이 알려 주는 수밖에 없다.

**요청이 늘지 않게 묶어서 받는다.** 앱이 메모리에 쌓아 두었다가 한 번에
올린다(`POST /trails`). 한 줄에 한 번씩 부르면 요청이 수십 배가 된다 —
성능 지표(`api_metrics`)가 분당 한 번 내려쓰는 것과 같은 판단이다.

`at` 이 **앱에서 실제로 일어난 시각**이고 `created_at` 은 서버에 닿은 시각이다.
둘이 다를 수 있다 — 묶어 보내므로 최대 10초쯤, 비행기 모드였으면 더 벌어진다.
**되짚을 때 봐야 하는 값은 `at` 이다.**

보존기간은 접속·활동 로그와 같다 (기본 90일, retention 잡이 파기).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class AppTrail(UUIDMixin, Base):
    __tablename__ = "app_trails"

    # 직원 하드삭제 시엔 NULL 로 이력 보존 — 활동 로그와 같은 규칙
    employee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )

    #: `SCREEN`(화면 이동) · `VIEW`(무엇을 열어 봤다)
    #:
    #: 갈라 두는 이유 — 화면 이동이 압도적으로 많아서 섞어 두면 정작 봐야 할
    #: 열람 기록이 묻힌다. 조회할 때 이 값으로 거른다.
    kind: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    #: 화면·동작 이름 (`급여` · `문서 열람`). **앱이 정하는 한국어 이름**이다
    screen: Mapped[str] = mapped_column(String(60), nullable=False)

    #: 무엇을 열었나 — 문서 이름·사람 이름·대화방 이름. `SCREEN` 이면 비어 있다
    #:
    #: **이름을 그대로 담는다.** id 만 담으면 그 문서가 지워진 뒤에 무엇을 봤는지
    #: 영영 알 수 없다 (전사 근태 달력이 이름을 그대로 싣는 것과 같은 이유).
    target: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #: 그 대상의 uuid — 아직 살아 있으면 이걸로 원본을 찾아간다
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    #: **앱에서 실제로 일어난 시각** (서버 도착 시각은 `created_at`)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    #: 올린 요청의 IP — 한 번에 여러 줄이 오므로 그 묶음 전체가 같은 값이다
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
