"""내 업무 DTO (2026-08-14)."""

from datetime import date, datetime

from pydantic import Field, field_validator

from app.enums import MyTaskRequestType, ProjectRequestStatus
from app.schemas.base import CamelModel

#: 안 고르면 매일 — 예전 동작이 그랬으므로 기본값을 바꾸지 않는다
EVERY_DAY = [1, 2, 3, 4, 5, 6, 7]


def clean_weekdays(value: list[int] | None) -> list[int]:
    """ISO 1(월)~7(일) 로 추리고 **차례대로 하나씩** 남긴다.

    `[7, 1, 1]` 처럼 겹치거나 뒤섞여 와도 `[1, 7]` 이 된다 — 화면이 요일을
    늘 같은 차례로 그려야 해서 여기서 한 번에 정리한다.
    비어 있으면 매일로 본다 (하나도 안 고른 업무는 영영 안 뜬다).
    """
    if not value:
        return list(EVERY_DAY)
    days = sorted({d for d in value if 1 <= d <= 7})
    return days or list(EVERY_DAY)


class MyTaskCreate(CamelModel):
    """한 번에 여러 개를 받는다 — **한 트랜잭션**이다.

    앱이 추가 화면에서 여러 줄을 쌓아 두고 한 번에 보낸다. 줄마다 따로
    부르면 중간에 끊겼을 때 **반만 들어간 채로 화면이 닫힌다.**

    **요일은 이 묶음 전체에 걸린다.** 한 번에 올리는 줄들은 같은 자리에서
    같이 적은 것이라 요일도 같다 — 줄마다 다르게 하려면 나눠서 올린다.
    """

    contents: list[str] = Field(min_length=1)
    #: 돌아오는 요일 (ISO 1~7). 안 주면 매일 — 예전과 같게 보인다
    weekdays: list[int] | None = None

    @field_validator("weekdays")
    @classmethod
    def _days(cls, v: list[int] | None) -> list[int]:
        return clean_weekdays(v)


class MyTaskOut(CamelModel):
    id: str
    employee_id: str
    content: str
    #: 돌아오는 요일 (ISO 1~7) — 앱이 목록 줄과 고르개에 그린다
    weekdays: list[int] = Field(default_factory=lambda: list(EVERY_DAY))
    sort: int
    #: **오늘 체크했나.** 목록을 받을 때 서버가 같이 채운다 —
    #: 앱이 체크 기록을 따로 받아 id 로 맞추면 요청이 두 배가 된다.
    checked: bool = False
    #: 대기 중인 수정·삭제 결재 (없으면 null) — 앱이 '대기' 표시를 그린다
    pending_request: "MyTaskRequestOut | None" = None
    created_at: datetime


class MyTaskDayOut(CamelModel):
    """하루치 내 업무 — 목록과 그날의 판정을 같이 준다."""

    date: date
    tasks: list[MyTaskOut]
    total: int
    done: int
    #: 다 했나 — 항목이 하나도 없으면 **완료가 아니다**(할 일을 안 정한 것이다)
    complete: bool


class MyTaskRosterRow(CamelModel):
    """대표·관리자가 보는 사람 한 줄 — 오늘 몇 개 중 몇 개를 했나.

    **이름을 그대로 싣는다.** 화면에 찍히는 값이 이름이라, uuid 로 주고 앱이
    명단에서 찾게 하면 명단을 못 받은 화면에서 빈칸이 된다
    (전사 근태 달력과 같은 판단 — backend-gap 70).
    """

    employee_id: str
    name: str
    total: int
    done: int
    complete: bool


class MyTaskRequestCreate(CamelModel):
    type: MyTaskRequestType
    #: EDIT 만 채운다 — `{"content": "..."}`
    payload: dict | None = None
    reason: str = Field(min_length=1)


class MyTaskRequestOut(CamelModel):
    id: str
    my_task_id: str
    type: MyTaskRequestType
    payload: dict | None = None
    reason: str
    status: ProjectRequestStatus
    requested_by_id: str
    decided_by_id: str | None = None
    decided_at: datetime | None = None
    reject_reason: str | None = None
    created_at: datetime
    #: 결재 화면이 "누가 무엇을" 을 보여줄 수 있게 서버가 채워 준다
    requester_name: str | None = None
    task_content: str | None = None
