"""내 업무 DTO (2026-08-14)."""

from datetime import date, datetime

from pydantic import Field

from app.enums import MyTaskRequestType, ProjectRequestStatus
from app.schemas.base import CamelModel


class MyTaskCreate(CamelModel):
    """한 번에 여러 개를 받는다 — **한 트랜잭션**이다.

    앱이 추가 화면에서 여러 줄을 쌓아 두고 한 번에 보낸다. 줄마다 따로
    부르면 중간에 끊겼을 때 **반만 들어간 채로 화면이 닫힌다.**
    """

    contents: list[str] = Field(min_length=1)


class MyTaskOut(CamelModel):
    id: str
    employee_id: str
    content: str
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
