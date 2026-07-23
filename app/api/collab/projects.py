"""Project 라우터 — CLAUDE.md §6.1. status 는 progress+due 파생."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import ProjectStatus, Role, ScoreCategory
from app.models.collab.project import Project
from app.models.org.employee import Employee
from app.models.scoring.score_event import ScoreEvent
from app.schemas.collab.project import (
    ProjectAwardCreate,
    ProjectAwardOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
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
    project_id: str, payload: ProjectUpdate, db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": "프로젝트를 찾을 수 없습니다"})
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    await db.commit()
    await db.refresh(project)
    return _to_out(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)) -> None:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": "프로젝트를 찾을 수 없습니다"})
    await db.delete(project)
    await db.commit()
    return None
