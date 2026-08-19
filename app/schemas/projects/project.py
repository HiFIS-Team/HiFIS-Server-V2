"""Project DTO — CLAUDE.md §6.1."""

from datetime import datetime

from pydantic import Field

from app.enums import ProjectActivityKind, ProjectStatus
from app.schemas.base import CamelModel


class ProjectCreate(CamelModel):
    title: str
    purpose: str = ""
    steps: str = ""
    start_at: datetime | None = None
    due: datetime
    progress: int = Field(default=0, ge=0, le=100)
    assignee_ids: list[str] = Field(default_factory=list)
    # 맡을 사람 — 안 주면 만든 사람이 담당이 된다
    owner_id: str | None = None
    color: str | None = None
    # 만들면서 같이 붙이는 체크리스트 — **한 트랜잭션으로 들어간다**
    #
    # 예전에는 앱이 프로젝트를 만든 뒤 할 일마다 `POST /todos` 를 따로 불렀다.
    # 그런데 그 라우트는 **이 프로젝트 사람만** 통과하므로(2026-08-14),
    # 대표·관리자가 남에게 맡기는 프로젝트를 만들면 자기가 멤버가 아니라
    # 할 일부터 403 이 났다 (실제로 겪었다). 만들기의 일부지 손대는 것이 아니다.
    todos: list["ProjectTodoCreate"] = Field(default_factory=list)


class ProjectUpdate(CamelModel):
    title: str | None = None
    purpose: str | None = None
    steps: str | None = None
    start_at: datetime | None = None
    due: datetime | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    assignee_ids: list[str] | None = None
    owner_id: str | None = None
    extension_reason: str | None = None
    color: str | None = None


class ProjectOut(CamelModel):
    id: str
    title: str
    purpose: str
    steps: str
    start_at: datetime | None = None
    due: datetime
    progress: int             # 체크리스트 있으면 완료율 자동, 없으면 수동값
    todo_count: int = 0       # 체크리스트 전체 개수
    done_count: int = 0       # 완료 개수
    assignee_ids: list[str]
    owner_id: str          # 맡은 사람 — 안 정했으면 만든 사람으로 채워서 준다
    color: str | None = None  # null=앱이 id 해시로 생성
    extension_reason: str | None = None
    status: ProjectStatus  # 서버 파생
    #: 완료한 시각 — **null 이면 아직 완료가 아니다** (2026-08-19).
    #: 할 일을 다 체크해도 담당자가 `/complete` 를 눌러야 채워진다.
    completed_at: datetime | None = None
    created_by_id: str
    created_at: datetime


class ProjectCommentCreate(CamelModel):
    body: str = Field(min_length=1)


class ProjectCommentUpdate(CamelModel):
    body: str = Field(min_length=1)


class ProjectActivityOut(CamelModel):
    """타임라인 항목 — kind=COMMENT 는 사용자 댓글, 나머지는 시스템 활동."""

    id: str
    project_id: str
    actor_id: str | None = None  # null=시스템
    kind: ProjectActivityKind
    body: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectTodoCreate(CamelModel):
    content: str
    assignee_id: str | None = None
    sort: int = 0


class ProjectTodoUpdate(CamelModel):
    content: str | None = None
    assignee_id: str | None = None
    done: bool | None = None
    sort: int | None = None


class ProjectTodoOut(CamelModel):
    id: str
    project_id: str
    content: str
    assignee_id: str | None = None
    done: bool
    sort: int
    created_by_id: str
    created_at: datetime


class ProjectAwardCreate(CamelModel):
    # 안 주면 담당자 **전원**에게 같은 점수 — 프로젝트는 다 같이 하는 일이라 보통 이쪽
    employee_id: str | None = None
    # 기본 10, 어드민 평가로 -100 ~ +100 (음수 = 본인 점수에서 차감)
    points: int = Field(default=10, ge=-100, le=100)
    comment: str  # 점수 부여 사유 필수


class ProjectAwardOut(CamelModel):
    id: str                      # ScoreEvent id
    project_id: str
    employee_id: str
    points: int
    comment: str | None = None   # 관리자 코멘트(= 점수 사유)
    created_by_id: str | None = None
    created_at: datetime
