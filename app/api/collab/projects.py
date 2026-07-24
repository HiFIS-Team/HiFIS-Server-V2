"""Project 라우터 — CLAUDE.md §6.1. status 는 progress+due 파생."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import (
    ProjectRequestStatus,
    ProjectRequestType,
    ProjectStatus,
    Role,
    ScoreCategory,
)
from app.models.collab.project import Project
from app.models.collab.project_request import ProjectRequest
from app.models.org.employee import Employee
from app.models.scoring.score_event import ScoreEvent
from app.schemas.collab.project import (
    ProjectAwardCreate,
    ProjectAwardOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from app.schemas.collab.project_request import (
    ProjectRequestCreate,
    ProjectRequestOut,
    ProjectRequestReject,
)
from app.services import notification_texts as ntext
from app.services.notifications import notify
from app.services.scoring import accrue_score

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(get_current_user)])


def _status(project: Project) -> ProjectStatus:
    if project.progress >= 100:
        return ProjectStatus.DONE
    if project.due < datetime.now(timezone.utc):
        return ProjectStatus.MISSED
    if project.progress > 0:
        return ProjectStatus.IN_PROGRESS
    return ProjectStatus.WAITING


def _to_out(project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        title=project.title,
        purpose=project.purpose,
        steps=project.steps,
        due=project.due,
        progress=project.progress,
        assignee_ids=project.assignee_ids,
        extension_reason=project.extension_reason,
        status=_status(project),
        created_by_id=project.created_by_id,
        created_at=project.created_at,
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    status: ProjectStatus | None = Query(None),
    assignee_id: str | None = Query(None, alias="assigneeId"),
    q: str | None = Query(None),
) -> list[ProjectOut]:
    stmt = select(Project)
    if assignee_id:
        stmt = stmt.where(Project.assignee_ids.contains([assignee_id]))
    if q:
        stmt = stmt.where(Project.title.ilike(f"%{q}%"))
    projects = (await db.execute(stmt.order_by(Project.created_at.desc()))).scalars().all()
    out = [_to_out(p) for p in projects]
    if status:  # 파생 상태 필터는 계산 후
        out = [o for o in out if o.status == status]
    return out


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    payload: ProjectCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    project = Project(
        title=payload.title,
        purpose=payload.purpose,
        steps=payload.steps,
        due=payload.due,
        progress=payload.progress,
        assignee_ids=payload.assignee_ids,
        created_by_id=current.id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return _to_out(project)


# ---------- 프로젝트 기한 변경 요청 (연장/누락 사유 → 어드민 승인) ----------
def _req_out(r: ProjectRequest) -> ProjectRequestOut:
    return ProjectRequestOut(
        id=r.id,
        project_id=r.project_id,
        type=r.type,
        new_due=r.new_due,
        reason=r.reason,
        status=r.status,
        requested_by_id=r.requested_by_id,
        decided_by_id=r.decided_by_id,
        decided_at=r.decided_at,
        reject_reason=r.reject_reason,
        created_at=r.created_at,
    )


# ⚠️ 리터럴 경로라 반드시 /{project_id} 보다 먼저 선언 (안 그러면 project_id="requests"로 잡힘)
@router.get("/requests", response_model=list[ProjectRequestOut])
async def list_project_requests(
    db: AsyncSession = Depends(get_db),
    status: ProjectRequestStatus | None = Query(None),
    project_id: str | None = Query(None, alias="projectId"),
) -> list[ProjectRequestOut]:
    stmt = select(ProjectRequest)
    if status:
        stmt = stmt.where(ProjectRequest.status == status)
    if project_id:
        stmt = stmt.where(ProjectRequest.project_id == project_id)
    rows = (await db.execute(stmt.order_by(ProjectRequest.created_at.desc()))).scalars().all()
    return [_req_out(r) for r in rows]


@router.post("/{project_id}/requests", response_model=ProjectRequestOut, status_code=201)
async def create_project_request(
    project_id: str,
    payload: ProjectRequestCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectRequestOut:
    """매니저·멤버가 기한 연장(EXTENSION)/누락 사유(OVERDUE)를 새 기한+사유로 제출."""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": "프로젝트를 찾을 수 없습니다"})
    # 프로젝트당 대기 요청은 하나만 (중복 방지)
    existing = await db.scalar(
        select(ProjectRequest).where(
            ProjectRequest.project_id == project_id,
            ProjectRequest.status == ProjectRequestStatus.PENDING,
        )
    )
    if existing is not None:
        raise HTTPException(400, detail={"code": "REQUEST_PENDING", "message": "이미 대기 중인 요청이 있습니다"})
    req = ProjectRequest(
        project_id=project_id,
        type=payload.type,
        new_due=payload.new_due,
        reason=payload.reason,
        requested_by_id=current.id,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    # 어드민에게 알림 (best-effort)
    label = "누락 사유" if payload.type == ProjectRequestType.OVERDUE else "기한 연장"
    admins = (await db.execute(select(Employee).where(Employee.role == Role.ADMIN))).scalars().all()
    for admin in admins:
        await notify(db, employee_id=admin.id, **ntext.project_request(label, project.title, current.name))
    await db.commit()
    return _req_out(req)


async def _decide_request(
    request_id: str,
    status: ProjectRequestStatus,
    db: AsyncSession,
    current: Employee,
    reason: str | None = None,
) -> ProjectRequestOut:
    req = await db.get(ProjectRequest, request_id)
    if req is None:
        raise HTTPException(404, detail={"code": "REQUEST_NOT_FOUND", "message": "요청을 찾을 수 없습니다"})
    if req.status != ProjectRequestStatus.PENDING:
        raise HTTPException(400, detail={"code": "ALREADY_DECIDED", "message": "이미 처리된 요청입니다"})
    project = await db.get(Project, req.project_id)
    req.status = status
    req.decided_by_id = current.id
    req.decided_at = datetime.now(timezone.utc)
    label = "누락 사유" if req.type == ProjectRequestType.OVERDUE else "기한 연장"
    title = project.title if project else ""
    if status == ProjectRequestStatus.APPROVED:
        if project is not None:
            project.due = req.new_due  # 새 기한 반영
            project.extension_reason = req.reason
            project.overdue_notified_at = None  # 마감 변경 → 누락 알림 재무장
    else:
        req.reject_reason = reason
    await notify(
        db,
        employee_id=req.requested_by_id,
        **ntext.project_request_decided(label, status == ProjectRequestStatus.APPROVED, title, reason),
    )
    await db.commit()
    await db.refresh(req)
    return _req_out(req)


@router.post("/requests/{request_id}/approve", response_model=ProjectRequestOut, dependencies=[Depends(require_role(Role.ADMIN))])
async def approve_project_request(
    request_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectRequestOut:
    return await _decide_request(request_id, ProjectRequestStatus.APPROVED, db, current)


@router.post("/requests/{request_id}/reject", response_model=ProjectRequestOut, dependencies=[Depends(require_role(Role.ADMIN))])
async def reject_project_request(
    request_id: str,
    payload: ProjectRequestReject,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectRequestOut:
    return await _decide_request(request_id, ProjectRequestStatus.REJECTED, db, current, payload.reason)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": "프로젝트를 찾을 수 없습니다"})
    return _to_out(project)


# ---------- 프로젝트 점수(달성 평가) ----------
def _award_out(event: ScoreEvent) -> ProjectAwardOut:
    return ProjectAwardOut(
        id=event.id,
        project_id=event.source_ref_id,
        employee_id=event.employee_id,
        points=event.points,
        comment=event.reason,
        created_by_id=event.created_by_id,
        created_at=event.created_at,
    )


@router.post("/{project_id}/award", response_model=ProjectAwardOut,
             dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def award_project(
    project_id: str,
    payload: ProjectAwardCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectAwardOut:
    """담당자에게 프로젝트 달성 점수 부여(기본 10, -100 ~ +100) + 코멘트. 재부여 시 갱신."""
    if not payload.comment.strip():
        raise HTTPException(400, detail={"code": "REASON_REQUIRED", "message": "점수 부여 사유는 필수입니다"})
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": "프로젝트를 찾을 수 없습니다"})
    if payload.employee_id not in project.assignee_ids:
        raise HTTPException(400, detail={"code": "NOT_ASSIGNEE", "message": "프로젝트 담당자가 아닙니다"})
    employee = await db.get(Employee, payload.employee_id)
    if employee is None:
        raise HTTPException(400, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "직원이 존재하지 않습니다"})

    # 같은 프로젝트·같은 직원은 하나만 — 재부여 시 점수·코멘트 갱신(재평가)
    existing = await db.scalar(
        select(ScoreEvent).where(
            ScoreEvent.category == ScoreCategory.PROJECT,
            ScoreEvent.source_ref_id == project_id,
            ScoreEvent.employee_id == payload.employee_id,
        )
    )
    if existing is not None:
        existing.points = payload.points
        existing.reason = payload.comment
        existing.created_by_id = current.id
        event = existing
    else:
        event = await accrue_score(
            db,
            employee_id=payload.employee_id,
            branch_id=employee.branch_id,
            category=ScoreCategory.PROJECT,
            points=payload.points,
            created_by_id=current.id,
            source_ref_id=project_id,
            reason=payload.comment,
        )
    await db.commit()
    await db.refresh(event)
    return _award_out(event)


@router.get("/{project_id}/awards", response_model=list[ProjectAwardOut])
async def list_project_awards(
    project_id: str, db: AsyncSession = Depends(get_db)
) -> list[ProjectAwardOut]:
    rows = await db.scalars(
        select(ScoreEvent)
        .where(
            ScoreEvent.category == ScoreCategory.PROJECT,
            ScoreEvent.source_ref_id == project_id,
        )
        .order_by(ScoreEvent.created_at.desc())
    )
    return [_award_out(e) for e in rows]


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": "프로젝트를 찾을 수 없습니다"})
    # ADMIN/MANAGER·작성자 = 전체 수정 / 담당자 = 진행률만 / 그 외 = 금지
    is_manager = current.role in (Role.ADMIN, Role.MANAGER) or project.created_by_id == current.id
    is_assignee = current.id in (project.assignee_ids or [])
    if not (is_manager or is_assignee):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "프로젝트를 수정할 권한이 없습니다"})
    fields = payload.model_dump(exclude_unset=True)
    if not is_manager and set(fields) - {"progress"}:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "담당자는 진행률만 변경할 수 있습니다"})
    for key, value in fields.items():
        setattr(project, key, value)
    if "due" in fields:  # 마감 변경 → 누락 알림 재무장
        project.overdue_notified_at = None
    await db.commit()
    await db.refresh(project)
    return _to_out(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": "프로젝트를 찾을 수 없습니다"})
    if current.role not in (Role.ADMIN, Role.MANAGER) and project.created_by_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "프로젝트를 삭제할 권한이 없습니다"})
    await db.delete(project)
    await db.commit()
    return None
