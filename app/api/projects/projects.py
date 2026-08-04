"""Project 라우터 — CLAUDE.md §6.1. status 는 progress+due 파생."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import (
    ProjectActivityKind,
    ProjectRequestStatus,
    ProjectRequestType,
    ProjectStatus,
    Role,
    ScoreCategory,
)
from app.models.projects.project import Project
from app.models.projects.project_activity import ProjectActivity
from app.models.projects.project_request import ProjectRequest
from app.models.projects.project_todo import ProjectTodo
from app.models.staff.employee import Employee
from app.models.scoring.score_event import ScoreEvent
from app.schemas.projects.project import (
    ProjectActivityOut,
    ProjectAwardCreate,
    ProjectAwardOut,
    ProjectCommentCreate,
    ProjectCommentUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectTodoCreate,
    ProjectTodoOut,
    ProjectTodoUpdate,
    ProjectUpdate,
)
from app.schemas.projects.project_request import (
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


def _to_out(project: Project, todo_count: int = 0, done_count: int = 0) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        title=project.title,
        purpose=project.purpose,
        steps=project.steps,
        start_at=project.start_at,
        due=project.due,
        progress=project.progress,
        todo_count=todo_count,
        done_count=done_count,
        assignee_ids=project.assignee_ids,
        # 이 컬럼이 생기기 전 프로젝트는 담당이 비어 있다 — 만든 사람으로 읽는다
        owner_id=project.owner_id or project.created_by_id,
        color=project.color,
        extension_reason=project.extension_reason,
        status=_status(project),
        created_by_id=project.created_by_id,
        created_at=project.created_at,
    )


async def _todo_counts(db: AsyncSession, project_ids: list[str]) -> dict[str, tuple[int, int]]:
    """프로젝트별 (전체, 완료) 체크리스트 개수 — 목록 N+1 없이 한 번에."""
    if not project_ids:
        return {}
    rows = (
        await db.execute(
            select(
                ProjectTodo.project_id,
                func.count(),
                func.count().filter(ProjectTodo.done.is_(True)),
            )
            .where(ProjectTodo.project_id.in_(project_ids))
            .group_by(ProjectTodo.project_id)
        )
    ).all()
    return {pid: (total, done) for pid, total, done in rows}


async def _single_out(db: AsyncSession, project: Project) -> ProjectOut:
    total, done = (await _todo_counts(db, [project.id])).get(project.id, (0, 0))
    return _to_out(project, total, done)


async def _recompute_progress(db: AsyncSession, project: Project) -> None:
    """체크리스트가 있으면 progress = 완료/전체 × 100. 없으면 수동값 유지."""
    total = await db.scalar(
        select(func.count()).select_from(ProjectTodo).where(ProjectTodo.project_id == project.id)
    )
    if total:
        done = await db.scalar(
            select(func.count())
            .select_from(ProjectTodo)
            .where(ProjectTodo.project_id == project.id, ProjectTodo.done.is_(True))
        )
        project.progress = round(done / total * 100)
    await _settle_completion(db, project)


# 완료하면 담당자마다 붙는 기본 점수. MASTER 가 여기서부터 올리거나 깎는다.
PROJECT_POINTS = 10


async def _settle_completion(db: AsyncSession, project: Project) -> None:
    """완료(100%)에 맞춰 담당자 점수를 정리한다. commit 은 호출자가 한다.

    - 100% 가 되면 담당자 **전원에게 기본 10점**. 이미 점수가 있는 사람은 건드리지
      않는다 — 되돌렸다 다시 완료해도 두 번 쌓이지 않는다.
    - 100% 아래로 내려가면 **자동으로 준 것만** 회수한다. MASTER 가 매긴 점수는
      그대로 둔다 (평가는 진행률과 별개로 내린 판단이라 되돌리면 안 된다).

    자동인지는 `created_by_id` 로 가른다 — 자동은 None, 사람이 준 것은 그 사람 id.
    """
    existing = (
        (
            await db.execute(
                select(ScoreEvent).where(
                    ScoreEvent.category == ScoreCategory.PROJECT,
                    ScoreEvent.source_ref_id == project.id,
                )
            )
        )
        .scalars()
        .all()
    )
    scored = {event.employee_id for event in existing}

    if project.progress >= 100:
        for employee_id in project.assignee_ids or []:
            if employee_id in scored:
                continue
            employee = await db.get(Employee, employee_id)
            if employee is None:
                continue
            await accrue_score(
                db,
                employee_id=employee_id,
                branch_id=employee.branch_id,
                category=ScoreCategory.PROJECT,
                points=PROJECT_POINTS,
                source_ref_id=project.id,
                reason="프로젝트 완료",
            )
        return

    for event in existing:
        if event.created_by_id is None:  # 사람이 매긴 점수는 남긴다
            await db.delete(event)


def _can_touch(project: Project, current: Employee) -> bool:
    # 체크리스트 편집 = 관리자·작성자·담당자
    return (
        current.role in (Role.MASTER, Role.ADMIN, Role.MANAGER)
        or project.created_by_id == current.id
        or current.id in (project.assignee_ids or [])
    )


def _ensure_open(project: Project, current: Employee) -> None:
    """완료된 프로젝트는 **MASTER 만** 손댈 수 있다.

    완료가 곧 점수라(`_settle_completion`) 되돌리면 담당자 점수도 같이 흔들린다.
    됐다 안 됐다 하는 걸 막으려고 잠그고, 실수로 완료한 것만 대표가 풀어 준다.

    댓글과 점수 부여(`award`)는 잠기지 않는다 — 완료 뒤에 판단해서 매기는 값이다.
    """
    if project.progress >= 100 and current.role != Role.MASTER:
        raise HTTPException(
            403,
            detail={"code": "PROJECT_DONE", "message": "완료된 프로젝트는 수정할 수 없습니다"},
        )


async def _log_activity(
    db: AsyncSession, project_id: str, actor_id: str | None, kind: ProjectActivityKind, body: str | None
) -> None:
    """상세 타임라인에 시스템 활동/댓글 1건 추가. commit 은 호출자."""
    db.add(ProjectActivity(project_id=project_id, actor_id=actor_id, kind=kind, body=body))


def _activity_out(a: ProjectActivity) -> ProjectActivityOut:
    return ProjectActivityOut(
        id=a.id,
        project_id=a.project_id,
        actor_id=a.actor_id,
        kind=a.kind,
        body=a.body,
        created_at=a.created_at,
        updated_at=a.updated_at,
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
    counts = await _todo_counts(db, [p.id for p in projects])
    out = [_to_out(p, *counts.get(p.id, (0, 0))) for p in projects]
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
        start_at=payload.start_at,
        due=payload.due,
        progress=payload.progress,
        assignee_ids=payload.assignee_ids,
        # 안 주면 만든 사람이 담당 — 직원·점장은 자기 일을 자기가 올린다
        owner_id=payload.owner_id or current.id,
        color=payload.color,
        created_by_id=current.id,
    )
    db.add(project)
    await db.flush()
    await _log_activity(db, project.id, current.id, ProjectActivityKind.CREATED, "프로젝트를 만들었어요")
    await _settle_completion(db, project)  # 드물지만 처음부터 100% 로 만드는 경우
    await db.commit()
    await db.refresh(project)
    return _to_out(project)  # 새 프로젝트는 체크리스트 0


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
    _ensure_open(project, current)
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
    # 승인권자(MASTER)에게 알림 (best-effort) — 승인·반려는 MASTER 전용
    label = "누락 사유" if payload.type == ProjectRequestType.OVERDUE else "기한 연장"
    await _log_activity(db, project_id, current.id, ProjectActivityKind.DUE, f"{label} 신청")  # 승인 전 신청도 타임라인
    approvers = (await db.execute(select(Employee).where(Employee.role == Role.MASTER))).scalars().all()
    for approver in approvers:
        await notify(db, employee_id=approver.id, **ntext.project_request(label, project.title, current.name))
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
            await _log_activity(db, project.id, current.id, ProjectActivityKind.DUE, f"{label} 승인 — 기한 변경")
    else:
        req.reject_reason = reason
        if project is not None:  # 반려도 타임라인
            await _log_activity(db, project.id, current.id, ProjectActivityKind.DUE, f"{label} 반려")
    await notify(
        db,
        employee_id=req.requested_by_id,
        **ntext.project_request_decided(label, status == ProjectRequestStatus.APPROVED, title, reason),
    )
    await db.commit()
    await db.refresh(req)
    return _req_out(req)


@router.post("/requests/{request_id}/approve", response_model=ProjectRequestOut, dependencies=[Depends(require_role(Role.MASTER))])
async def approve_project_request(
    request_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectRequestOut:
    return await _decide_request(request_id, ProjectRequestStatus.APPROVED, db, current)


@router.post("/requests/{request_id}/reject", response_model=ProjectRequestOut, dependencies=[Depends(require_role(Role.MASTER))])
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
    return await _single_out(db, project)


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
             dependencies=[Depends(require_role(Role.MASTER))])
async def award_project(
    project_id: str,
    payload: ProjectAwardCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectAwardOut:
    """담당자 점수 조정 — **MASTER 만**.

    완료하면 자동으로 10점이 붙는다. 그 위에서 대표가 판단해 올리거나 깎는다 —
    기한 안에 힘든 걸 해냈으면 최대 100, 완료라고만 찍고 실제로 안 했으면 -100.
    여기서 주는 값이 그 사람이 이 프로젝트에서 받는 **최종 점수**다 (더해지지 않는다).

    재부여하면 갱신된다. 한 번 사람이 손대면 진행률이 내려가도 회수되지 않는다.
    """
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


# ---------- 프로젝트 체크리스트 (완료율 → progress 자동) ----------
def _todo_out(t: ProjectTodo) -> ProjectTodoOut:
    return ProjectTodoOut(
        id=t.id,
        project_id=t.project_id,
        content=t.content,
        assignee_id=t.assignee_id,
        done=t.done,
        sort=t.sort,
        created_by_id=t.created_by_id,
        created_at=t.created_at,
    )


async def _get_project_or_404(db: AsyncSession, project_id: str) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": "프로젝트를 찾을 수 없습니다"})
    return project


async def _get_todo_or_404(db: AsyncSession, project_id: str, todo_id: str) -> ProjectTodo:
    todo = await db.get(ProjectTodo, todo_id)
    if todo is None or todo.project_id != project_id:
        raise HTTPException(404, detail={"code": "TODO_NOT_FOUND", "message": "체크리스트 항목을 찾을 수 없습니다"})
    return todo


@router.get("/{project_id}/todos", response_model=list[ProjectTodoOut])
async def list_project_todos(project_id: str, db: AsyncSession = Depends(get_db)) -> list[ProjectTodoOut]:
    await _get_project_or_404(db, project_id)
    rows = (
        await db.execute(
            select(ProjectTodo)
            .where(ProjectTodo.project_id == project_id)
            .order_by(ProjectTodo.sort, ProjectTodo.created_at)
        )
    ).scalars().all()
    return [_todo_out(t) for t in rows]


@router.post("/{project_id}/todos", response_model=ProjectTodoOut, status_code=201)
async def create_project_todo(
    project_id: str,
    payload: ProjectTodoCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectTodoOut:
    project = await _get_project_or_404(db, project_id)
    if not _can_touch(project, current):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "체크리스트를 편집할 권한이 없습니다"})
    _ensure_open(project, current)
    todo = ProjectTodo(
        project_id=project_id,
        content=payload.content,
        assignee_id=payload.assignee_id,
        sort=payload.sort,
        created_by_id=current.id,
    )
    db.add(todo)
    await db.flush()
    await _recompute_progress(db, project)  # 항목 추가 → 진행률 재계산
    await db.commit()
    await db.refresh(todo)
    return _todo_out(todo)


@router.patch("/{project_id}/todos/{todo_id}", response_model=ProjectTodoOut)
async def update_project_todo(
    project_id: str,
    todo_id: str,
    payload: ProjectTodoUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectTodoOut:
    todo = await _get_todo_or_404(db, project_id, todo_id)
    project = await _get_project_or_404(db, project_id)
    if not _can_touch(project, current):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "체크리스트를 편집할 권한이 없습니다"})
    _ensure_open(project, current)
    was_done = todo.done
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(todo, key, value)
    await db.flush()
    await _recompute_progress(db, project)  # 완료 토글 → 진행률 재계산
    if todo.done and not was_done:  # 완료로 바뀜 → 타임라인
        await _log_activity(db, project_id, current.id, ProjectActivityKind.TODO, f"완료: {todo.content}")
    elif was_done and not todo.done:  # 완료 취소 → 타임라인
        await _log_activity(db, project_id, current.id, ProjectActivityKind.TODO, f"완료 취소: {todo.content}")
    await db.commit()
    await db.refresh(todo)
    return _todo_out(todo)


@router.delete("/{project_id}/todos/{todo_id}", status_code=204)
async def delete_project_todo(
    project_id: str,
    todo_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    todo = await _get_todo_or_404(db, project_id, todo_id)
    project = await _get_project_or_404(db, project_id)
    if not _can_touch(project, current):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "체크리스트를 편집할 권한이 없습니다"})
    _ensure_open(project, current)
    content = todo.content  # 삭제 전 스냅샷(타임라인 표시용)
    await db.delete(todo)
    await db.flush()
    await _recompute_progress(db, project)
    await _log_activity(db, project_id, current.id, ProjectActivityKind.TODO, f"할 일 삭제: {content}")
    await db.commit()
    return None


# ---------- 상세 타임라인 (활동 기록 + 댓글) ----------
@router.get("/{project_id}/activities", response_model=list[ProjectActivityOut])
async def list_project_activities(
    project_id: str, db: AsyncSession = Depends(get_db)
) -> list[ProjectActivityOut]:
    """댓글(kind=COMMENT) + 시스템 활동을 최신순 한 타임라인으로."""
    await _get_project_or_404(db, project_id)
    rows = (
        await db.execute(
            select(ProjectActivity)
            .where(ProjectActivity.project_id == project_id)
            .order_by(ProjectActivity.created_at.desc())
        )
    ).scalars().all()
    return [_activity_out(a) for a in rows]


@router.post("/{project_id}/comments", response_model=ProjectActivityOut, status_code=201)
async def create_project_comment(
    project_id: str,
    payload: ProjectCommentCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectActivityOut:
    await _get_project_or_404(db, project_id)
    comment = ProjectActivity(
        project_id=project_id, actor_id=current.id, kind=ProjectActivityKind.COMMENT, body=payload.body
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return _activity_out(comment)


async def _get_comment_or_404(db: AsyncSession, project_id: str, comment_id: str) -> ProjectActivity:
    c = await db.get(ProjectActivity, comment_id)
    if c is None or c.project_id != project_id or c.kind != ProjectActivityKind.COMMENT:
        raise HTTPException(404, detail={"code": "COMMENT_NOT_FOUND", "message": "댓글을 찾을 수 없습니다"})
    return c


@router.patch("/{project_id}/comments/{comment_id}", response_model=ProjectActivityOut)
async def update_project_comment(
    project_id: str,
    comment_id: str,
    payload: ProjectCommentUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectActivityOut:
    comment = await _get_comment_or_404(db, project_id, comment_id)
    if comment.actor_id != current.id:  # 본인 댓글만 수정
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 댓글만 수정할 수 있습니다"})
    comment.body = payload.body
    await db.commit()
    await db.refresh(comment)
    return _activity_out(comment)


@router.delete("/{project_id}/comments/{comment_id}", status_code=204)
async def delete_project_comment(
    project_id: str,
    comment_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    comment = await _get_comment_or_404(db, project_id, comment_id)
    # 본인 댓글 또는 관리자(모더레이션)
    if comment.actor_id != current.id and current.role not in (Role.MASTER, Role.ADMIN, Role.MANAGER):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 댓글 또는 관리자만 삭제할 수 있습니다"})
    await db.delete(comment)
    await db.commit()
    return None


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
    is_manager = current.role in (Role.MASTER, Role.ADMIN, Role.MANAGER) or project.created_by_id == current.id
    is_assignee = current.id in (project.assignee_ids or [])
    if not (is_manager or is_assignee):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "프로젝트를 수정할 권한이 없습니다"})
    _ensure_open(project, current)
    fields = payload.model_dump(exclude_unset=True)
    if not is_manager and set(fields) - {"progress"}:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "담당자는 진행률만 변경할 수 있습니다"})
    old_progress, old_due = project.progress, project.due
    old_assignees = set(project.assignee_ids or [])
    for key, value in fields.items():
        setattr(project, key, value)
    if "due" in fields:  # 마감 변경 → 누락 알림 재무장
        project.overdue_notified_at = None
    # 변경 타임라인 (수정된 것만)
    if "progress" in fields and project.progress != old_progress:
        await _log_activity(db, project_id, current.id, ProjectActivityKind.PROGRESS, f"진행률 {project.progress}%")
    if "due" in fields and project.due != old_due:
        await _log_activity(db, project_id, current.id, ProjectActivityKind.DUE, "기한을 변경했어요")
    if "assignee_ids" in fields and set(project.assignee_ids or []) != old_assignees:
        await _log_activity(db, project_id, current.id, ProjectActivityKind.ASSIGNEE, "담당자를 변경했어요")
    # 진행률을 손으로 바꾸거나 담당자가 늘면 완료 점수를 다시 셈한다
    # (체크리스트 쪽은 _recompute_progress 안에서 이미 부른다)
    if "progress" in fields or "assignee_ids" in fields:
        await _settle_completion(db, project)
    await db.commit()
    await db.refresh(project)
    return await _single_out(db, project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": "프로젝트를 찾을 수 없습니다"})
    if current.role not in (Role.MASTER, Role.ADMIN, Role.MANAGER) and project.created_by_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "프로젝트를 삭제할 권한이 없습니다"})
    _ensure_open(project, current)
    # 자식(FK) 먼저 정리 — 체크리스트·기한변경요청·타임라인
    await db.execute(delete(ProjectTodo).where(ProjectTodo.project_id == project_id))
    await db.execute(delete(ProjectRequest).where(ProjectRequest.project_id == project_id))
    await db.execute(delete(ProjectActivity).where(ProjectActivity.project_id == project_id))
    # 완료 점수도 같이 지운다. `source_ref_id` 는 FK 가 아니라 그냥 두면 남는데,
    # 없어진 프로젝트 때문에 랭킹 점수가 올라가 있고 근거를 찾을 길이 없게 된다.
    await db.execute(
        delete(ScoreEvent).where(
            ScoreEvent.category == ScoreCategory.PROJECT,
            ScoreEvent.source_ref_id == project_id,
        )
    )
    await db.delete(project)
    await db.commit()
    return None
