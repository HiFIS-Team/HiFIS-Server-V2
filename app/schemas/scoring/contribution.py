"""ContributionGrant DTO — CLAUDE.md §4.4."""

from datetime import datetime

from pydantic import Field

from app.enums import ContribType
from app.schemas.base import CamelModel


#: 자발적 목표 업무의 점수 범위 — **주는 사람이 고른다** (2026-09-21 대표 요청)
#:
#: 예전에는 10점 고정이었다. 큰 목표와 작은 목표가 같은 값을 받아서,
#: 매기는 쪽이 무게를 실을 자리가 없었다.
#:
#: **창의적 아이디어(3)·근무 외 출근(10)은 그대로 고정이다.** 아이디어는
#: 낸 것 자체를 세는 값이고, 근무 외 출근은 시간이 정하는 값이라 사람이
#: 고를 것이 없다.
GOAL_POINTS_MIN = 5
GOAL_POINTS_MAX = 20


class ContributionCreate(CamelModel):
    employee_id: str
    type: ContribType
    hours: int | None = Field(default=None, gt=0)  # EXTRA_WORK 필수
    #: 자발적 목표 업무의 점수 — `5`~`20`. **안 주면 서버 기본값**(10)이다.
    #:
    #: 다른 갈래에 실려 오면 **400 이다** (조용히 버리면 20점을 줬다고
    #: 생각한 사람이 3점이 들어간 것을 모른다).
    points: int | None = Field(
        default=None, ge=GOAL_POINTS_MIN, le=GOAL_POINTS_MAX
    )
    reason: str


class ContributionGrantOut(CamelModel):
    id: str
    employee_id: str
    type: ContribType
    hours: int | None = None
    points: int
    reason: str
    granted_by_id: str
    created_at: datetime
