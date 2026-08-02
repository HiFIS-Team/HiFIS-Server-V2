"""ProjectRequest DTO — 프로젝트 기한 변경 요청(연장/누락 사유)."""

from datetime import datetime

from pydantic import Field

from app.enums import ProjectRequestStatus, ProjectRequestType
from app.schemas.base import CamelModel


class ProjectRequestCreate(CamelModel):
    type: ProjectRequestType
    new_due: datetime
    reason: str = Field(min_length=1)  # 연장/누락 사유 필수


class ProjectRequestReject(CamelModel):
    reason: str = Field(min_length=1)  # 반려 사유 필수


class ProjectRequestOut(CamelModel):
    id: str
    project_id: str
    type: ProjectRequestType
    new_due: datetime
    reason: str
    status: ProjectRequestStatus
    requested_by_id: str
    decided_by_id: str | None = None
    decided_at: datetime | None = None
    reject_reason: str | None = None
    created_at: datetime
