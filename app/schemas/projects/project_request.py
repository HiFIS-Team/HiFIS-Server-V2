"""ProjectRequest DTO — 프로젝트 결재 요청(기한 연장·누락 사유·수정·삭제)."""

from datetime import datetime

from pydantic import Field, model_validator

from app.enums import ProjectRequestStatus, ProjectRequestType
from app.schemas.base import CamelModel


class ProjectEditPayload(CamelModel):
    """수정 신청이 담는 '이렇게 바꾸겠다' — 안 준 칸은 안 바뀐다.

    **이름·설명·색뿐이다** (2026-08-14 결정). 기한은 연장 신청이 따로 맡고,
    담당자·참여 멤버는 바꾸는 순간 사람이 잠기고 할 일 담당도 비워져서
    성격이 다르다 — 필요해지면 그때 따로 정한다.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    purpose: str | None = None
    color: str | None = Field(default=None, max_length=20)

    def any_set(self) -> bool:
        return any(v is not None for v in (self.title, self.purpose, self.color))


class ProjectMembersPayload(CamelModel):
    """인원 추가 신청이 담는 것 — **넣을 사람만** (2026-08-19).

    **빼는 길은 일부러 안 만들었다.** 할 일(`ProjectTodo.assignee_id`)이 사람을
    가리키고 있어서, 참여 인원에서 빼면 그 사람에게 걸린 할 일이 붕 뜬다.
    무엇으로 대신할지 정해야 하는 문제라 추가만 먼저 연다.
    """

    add_ids: list[str] = Field(min_length=1, max_length=30)


class ProjectRequestCreate(CamelModel):
    type: ProjectRequestType
    # EXTENSION·OVERDUE 만 쓴다
    new_due: datetime | None = None
    # EDIT 만 쓴다
    payload: ProjectEditPayload | None = None
    # MEMBERS 만 쓴다
    members: ProjectMembersPayload | None = None
    reason: str = Field(min_length=1)  # 종류 불문 사유 필수

    @model_validator(mode="after")
    def _check_shape(self) -> "ProjectRequestCreate":
        """종류마다 채워야 할 칸이 다르다 — 라우터에 흩어 두면 놓친다."""
        if self.type in (ProjectRequestType.EXTENSION, ProjectRequestType.OVERDUE):
            if self.new_due is None:
                raise ValueError("기한 연장·누락 사유에는 새 기한이 필요합니다")
        elif self.type is ProjectRequestType.EDIT:
            if self.payload is None or not self.payload.any_set():
                raise ValueError("수정 신청에는 바꿀 값이 하나 이상 필요합니다")
        elif self.type is ProjectRequestType.MEMBERS:
            if self.members is None:
                raise ValueError("인원 추가 신청에는 넣을 사람이 필요합니다")
        return self


class ProjectRequestReject(CamelModel):
    reason: str = Field(min_length=1)  # 반려 사유 필수


class ProjectRequestOut(CamelModel):
    id: str
    project_id: str
    type: ProjectRequestType
    new_due: datetime | None = None
    payload: ProjectEditPayload | None = None
    members: ProjectMembersPayload | None = None
    reason: str
    status: ProjectRequestStatus
    requested_by_id: str
    decided_by_id: str | None = None
    decided_at: datetime | None = None
    reject_reason: str | None = None
    created_at: datetime
