"""Branch (지점) 모델 — CLAUDE.md §2.1."""

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Branch(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "branches"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="BRANCH")  # HQ | BRANCH

    #: 프로젝트·회의록을 **서로 보여 줄 지점 묶음** (2026-08-19 대표 결정).
    #:
    #: 같은 값끼리만 서로 본다 — 지금은 `첨단`·`화순` 이 `A`, `동광주` 가 `B` 다.
    #: 동광주에서 앱 화면이 밖으로 나간 일이 있어 갈라 두기로 했다.
    #:
    #: **`NULL` 은 전 지점**이다 — 본사(HQ)가 그렇고, 거기 사람은 전부 보며
    #: 거기서 만든 것도 모두에게 보인다. 대표가 만든 전사 프로젝트가
    #: 한 지점에만 안 보이면 안 되기 때문이다.
    #:
    #: **코드에 지점 이름을 박지 않으려고 컬럼으로 뒀다.** 지점이 늘거나 묶음이
    #: 바뀌어도 이 값만 고치면 되고 배포가 필요 없다.
    share_group: Mapped[str | None] = mapped_column(String(20), nullable=True)

    #: 회원 설문 QR 이 담는 값 — `/survey/{survey_token}`.
    #:
    #: **지점 id 를 그대로 쓰지 않는다.** 매장 벽에 붙는 것이라 언젠가 새어 나가는데,
    #: id 면 갈아 끼울 방법이 없다. 토큰이면 새 값을 넣고 QR 만 다시 뽑으면 된다.
    survey_token: Mapped[str | None] = mapped_column(
        String(32), unique=True, index=True, nullable=True
    )

    #: 매장 TV 가 여는 주소 — `/tv/{tv_token}`.
    #:
    #: **설문 토큰과 따로 둔다.** 설문 토큰은 글을 *쓰는* 열쇠라, TV 주소창에
    #: 띄워 두면 그 앞을 지나는 누구나 가짜 칭찬을 넣을 수 있다.
    #: 이건 읽기만 하는 값이라 새어도 화면이 한 장 더 보이는 것뿐이다.
    tv_token: Mapped[str | None] = mapped_column(
        String(32), unique=True, index=True, nullable=True
    )

    #: 출석 이력을 여는 주소 — `/history/{history_token}` (2026-08-26).
    #:
    #: **TV 토큰을 같이 쓰면 안 된다.** 저건 매장 벽에 걸리는 값인데 이 화면에는
    #: **회원 이름·전화·출석일이 줄줄이** 뜬다. 벽에 걸린 주소를 아는 사람이
    #: 곧 회원 명단을 보게 된다.
    #:
    #: 브로제이를 쓰는 지점이 화순뿐이라 실제로는 거기만 발급한다.
    history_token: Mapped[str | None] = mapped_column(
        String(32), unique=True, index=True, nullable=True
    )

    #: 출퇴근 QR 이 담는 값 — 매장 카운터에 붙는 종이다 (2026-08-28).
    #:
    #: **설문 토큰과 같은 이유로 지점 id 를 안 쓴다.** 벽에 붙는 것이라 언젠가
    #: 새는데, id 면 갈아 끼울 방법이 없다. 새면 값을 바꾸고 QR 만 다시 뽑는다.
    scan_secret: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: 그 지점 인터넷의 공인 IP 들 — **QR 을 여기서 찍었는지 가르는 값**이다.
    #:
    #: 고정 QR 이라 사진을 찍어 두면 집에서도 찍힌다. 그래서 요청이 그 지점
    #: 인터넷에서 왔는지를 같이 본다. 대표가 지점에서 버튼 한 번 누르면
    #: 지금 IP 가 여기 담긴다 (`POST /branches/{id}/scan-ip`).
    #:
    #: **비어 있으면 QR 스캔이 아예 안 된다** — 열어 두면 어디서나 찍힌다.
    #: 회선이 동적이라 IP 가 바뀌면 그날 아무도 못 찍으니, 바뀌면 다시 누른다.
    allowed_ips: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )

    #: 다짐(Dagym) 지점 키 — 출석 이력을 받을 때 `x-gym-id` 헤더로 보낸다.
    #:
    #: **지점마다 값이 다르다.** 채워져 있으면 그 지점은 다짐에서 출석을 받고,
    #: 비어 있으면 브로제이 쪽을 본다 (브로제이는 그룹이 하나라 설정에 있다).
    dajim_gym_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
