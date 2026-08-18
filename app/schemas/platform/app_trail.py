"""앱 사용 기록 스키마 — 모델 설명은 `app/models/platform/app_trail.py`."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel

#: 한 번에 받는 최대 줄 수 — 앱이 10초마다 올리므로 평소엔 열 몇 줄이다.
#: 비행기 모드로 오래 쓰다 돌아오면 밀린 것이 한꺼번에 오는데, 그때도
#: 요청 하나가 지나치게 커지지 않게 앱이 잘라서 나눠 보낸다.
TRAIL_BATCH_MAX = 200


class TrailItem(CamelModel):
    """앱에서 일어난 일 한 줄."""

    #: SCREEN(화면 이동) · VIEW(무엇을 열어 봤다)
    kind: Literal["SCREEN", "VIEW"] = "SCREEN"

    #: 화면·동작 이름 (`급여` · `문서 열람`)
    screen: str = Field(max_length=60)

    #: 무엇을 열었나 — 문서 이름·사람 이름 등. SCREEN 이면 비운다
    target: str | None = Field(default=None, max_length=120)

    #: 그 대상의 uuid
    target_id: str | None = Field(default=None, max_length=36)

    #: **앱에서 실제로 일어난 시각.** 서버 도착 시각과 다르다 (묶어 보내므로)
    at: datetime


class TrailBatch(CamelModel):
    """묶어서 올리는 것 — 줄마다 요청을 내면 요청 수가 수십 배가 된다."""

    items: list[TrailItem] = Field(max_length=TRAIL_BATCH_MAX)


class TrailOut(CamelModel):
    id: str
    employee_id: str | None
    #: 이름을 같이 준다 — 조회 화면이 사람마다 명단을 뒤지지 않아도 되게
    employee_name: str | None = None
    kind: str
    screen: str
    target: str | None
    target_id: str | None
    at: datetime
    ip: str | None
