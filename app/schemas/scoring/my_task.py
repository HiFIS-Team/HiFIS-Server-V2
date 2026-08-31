"""내 업무 DTO (2026-08-14)."""

from datetime import date, datetime

from pydantic import Field, field_validator

from app.enums import MyTaskFieldKind, MyTaskRequestType, ProjectRequestStatus
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


#: 업무 하나에 붙일 수 있는 입력 칸 수 — 사람이 체크하며 채우는 값이라 이 위는 사고다
MAX_FIELDS = 5


class MyTaskField(CamelModel):
    """체크할 때 받을 칸 하나 — 이름과 종류 (2026-08-31 요청).

    `신규`(숫자) · `재등록`(숫자) 처럼 업무 하나에 여러 개를 걸 수 있다.
    """

    name: str = Field(min_length=1, max_length=20)
    kind: MyTaskFieldKind = MyTaskFieldKind.NUMBER


def clean_fields(value: list[MyTaskField] | None) -> list[dict]:
    """**같은 이름을 두 번 두지 않는다.** 값이 이름을 키로 담기므로 겹치면 덮인다."""
    if not value:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for f in value:
        name = f.name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "kind": f.kind.value})
    if len(out) > MAX_FIELDS:
        raise ValueError("입력 칸이 너무 많아요")
    return out


class MyTaskItem(CamelModel):
    """만들 업무 한 줄 — 내용과 그 줄에 걸리는 요일."""

    content: str
    #: 안 주면 매일
    weekdays: list[int] | None = None
    #: 체크할 때 받을 칸 — 안 주면 없다(누르기만 하면 된다)
    fields: list[MyTaskField] | None = None

    @field_validator("weekdays")
    @classmethod
    def _days(cls, v: list[int] | None) -> list[int]:
        return clean_weekdays(v)


class MyTaskCreate(CamelModel):
    """한 번에 여러 개를 받는다 — **한 트랜잭션**이다.

    앱이 추가 화면에서 여러 줄을 쌓아 두고 한 번에 보낸다. 줄마다 따로
    부르면 중간에 끊겼을 때 **반만 들어간 채로 화면이 닫힌다.**

    보내는 길이 둘이다.

    | 칸 | 언제 |
    |---|---|
    | `items` | **줄마다 요일이 다를 때** — 요일을 하나씩 훑으며 담는 화면 |
    | `contents` + `weekdays` | 한 묶음이 같은 요일일 때 (옛 모양, 그대로 받는다) |

    둘 다 비면 400 이다 (`CONTENT_REQUIRED`).
    """

    contents: list[str] | None = None
    #: `contents` 와 짝 — 그 묶음 전체에 걸린다. 안 주면 매일
    weekdays: list[int] | None = None
    items: list[MyTaskItem] | None = None

    @field_validator("weekdays")
    @classmethod
    def _days(cls, v: list[int] | None) -> list[int]:
        return clean_weekdays(v)

    def rows(self) -> list[tuple[str, list[int], list[dict]]]:
        """어느 길로 왔든 `(내용, 요일, 입력 칸)` 목록 하나로 만들어 준다.

        옛 모양(`contents`)에는 입력 칸이 없다 — 그때는 그런 개념이 없었다.
        """
        if self.items:
            return [
                (i.content, i.weekdays or list(EVERY_DAY), clean_fields(i.fields))
                for i in self.items
            ]
        days = self.weekdays or list(EVERY_DAY)
        return [(c, days, []) for c in (self.contents or [])]


class MyTaskUpdate(CamelModel):
    """**한 번도 체크한 적 없는** 업무를 결재 없이 바로 고칠 때 (2026-08-20).

    안 보낸 칸은 지금 값을 그대로 둔다 — 요일만 고치거나 내용만 고칠 수 있다.
    """

    content: str | None = None
    weekdays: list[int] | None = None
    #: 통째로 갈아 끼운다 — 빈 배열을 주면 칸이 없어진다
    fields: list[MyTaskField] | None = None


class MyTaskCheckCreate(CamelModel):
    """체크하면서 적어 넣는 값 — `{"신규": "3", "재등록": "5"}` (2026-08-31).

    **글자로 받는다.** 숫자 칸은 서버가 `int` 로 바꿔 담고, 못 바꾸면 400 이다 —
    앱이 미리 걸러도 서버가 마지막으로 본다.
    """

    values: dict[str, str] = Field(default_factory=dict)


class MyTaskOut(CamelModel):
    id: str
    employee_id: str
    content: str
    #: 돌아오는 요일 (ISO 1~7) — 앱이 목록 줄과 고르개에 그린다
    weekdays: list[int] = Field(default_factory=lambda: list(EVERY_DAY))
    #: 체크할 때 받을 칸 — 비어 있으면 누르기만 하면 된다
    fields: list[MyTaskField] = Field(default_factory=list)
    #: **그날 적어 넣은 값** — 체크를 안 했으면 비어 있다
    values: dict = Field(default_factory=dict)
    sort: int
    #: **오늘 체크했나.** 목록을 받을 때 서버가 같이 채운다 —
    #: 앱이 체크 기록을 따로 받아 id 로 맞추면 요청이 두 배가 된다.
    checked: bool = False
    #: **한 번이라도 체크한 적이 있나** (오늘이 아니라 통틀어서, 2026-08-20).
    #:
    #: 앱이 수정·삭제를 어느 길로 보낼지 이 값으로 가른다 — 아직 한 번도
    #: 안 했으면 바로 고치고, 한 번이라도 했으면 결재를 받는다.
    ever_checked: bool = False
    #: **밀려 온 것이면 원래 차례였던 날** (2026-08-20 요청). null 이면 제 차례다.
    #:
    #: 그날 못 한 업무는 다음 근무일 목록 **뒤에** 붙어서 온다 —
    #: 앱이 이 값으로 구분선 아래에 그린다.
    carried_from: date | None = None
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


class MyTaskExcuseCreate(CamelModel):
    """누락 사유서 — 왜 못 했는지 (2026-08-21).

    **사유가 필수다.** 빈 사유서를 받아 두면 결재하는 쪽이 판단할 근거가 없다.
    """

    reason: str = Field(min_length=1)


class MyTaskMissOut(CamelModel):
    """확정 누락 한 줄 — 본인 화면과 대표 결재함이 같이 쓴다."""

    id: str
    employee_id: str
    date: date
    task_count: int
    #: 그날 못 한 업무 이름들 — 나중에 업무를 고쳐도 그때 것이 남아 있다
    contents: list[str] | None = None
    #: `None` 이면 사유서를 아직 안 냈다
    excuse_reason: str | None = None
    #: `None` 안 냄 · PENDING 대기 · APPROVED **회복** · REJECTED 확정
    excuse_status: ProjectRequestStatus | None = None
    decided_by_id: str | None = None
    decided_at: datetime | None = None
    reject_reason: str | None = None
    created_at: datetime
    #: 결재 화면이 '누가' 를 보여줄 수 있게 서버가 채워 준다
    employee_name: str | None = None


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
