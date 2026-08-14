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
from app.models.scoring.env import EnvItem, EnvTaskLog
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
    ProjectEditPayload,
    ProjectRequestCreate,
    ProjectRequestOut,
    ProjectRequestReject,
)
from app.services import notification_texts as ntext
from app.services.notifications import notify, notify_bosses
from app.services.scoring import accrue_score, scores_apply_to

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

    - 100% 가 되면 담당자 **전원에게 무조건 기본 10점**을 먼저 준다 (2026-08-13 결정).
      MASTER 가 완료 **전에** 점수를 매겨 뒀어도 10점으로 되돌린다 — 깎거나 더 주는
      것은 완료된 다음에 하는 판단이라, 완료 시점의 출발선은 항상 10점이다.
    - 100% 아래로 내려가면 **자동으로 준 것만** 회수한다. MASTER 가 매긴 점수는
      그대로 둔다 (평가는 진행률과 별개로 내린 판단이라 되돌리면 안 된다).

    자동인지는 `created_by_id` 로 가른다 — 자동은 None, 사람이 준 것은 그 사람 id.

    **정산은 완료 한 번에 한 번만** 한다 (`completed_notified_at` 이 표시). 이 함수는
    진행률을 건드릴 때마다 불려서, 표시가 없으면 100% 인 프로젝트의 할 일을 체크할
    때마다 MASTER 가 매긴 점수가 10점으로 되돌아간다.
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
    by_employee = {event.employee_id: event for event in existing}

    if project.progress >= 100:
        # 이미 이번 완료로 정산했으면 아무것도 안 한다 (MASTER 평가를 덮지 않는다)
        if project.completed_notified_at is not None:
            return
        for employee_id in project.assignee_ids or []:
            employee = await db.get(Employee, employee_id)
            if employee is None:
                continue
            event = by_employee.get(employee_id)
            if event is not None:
                # 완료 전에 매겨 둔 점수가 있어도 출발선은 10점이다
                event.points = PROJECT_POINTS
                event.reason = "프로젝트 완료"
                event.created_by_id = None  # 다시 자동으로 — 되돌리면 회수 대상이 된다
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
        # 대표·관리자에게 완료를 알린다 (2026-08-11 대표 요청).
        project.completed_notified_at = datetime.now(timezone.utc)
        await notify_bosses(db, **ntext.project_completed(project.title, project.id))
        return

    # 100% 아래로 내려갔다 — 다시 완료하면 그때 또 알린다
    project.completed_notified_at = None
    for event in existing:
        if event.created_by_id is None:  # 사람이 매긴 점수는 남긴다
            await db.delete(event)


# ---------- 프로젝트 할 일 ↔ 환경정비 (2026-08-14) ----------

#: 손으로 적는 칸이라 매칭에서 뺀다 — `기타 정리` 같은 할 일이 전부 걸린다
_ENV_MATCH_EXCLUDE = {"기타"}


async def _env_item_for(db: AsyncSession, branch_id: str, content: str) -> EnvItem | None:
    """할 일 내용에서 그 지점의 환경정비 항목을 찾는다 — **단어가 똑같을 때만.**

    `현수막 설치 1` → 단어 `현수막` `설치` `1` 중 `현수막` 이 항목 이름과
    정확히 같아서 걸린다. `세탁기 수리` 는 **안 걸린다** (`세탁기` ≠ `세탁`) —
    글자가 들어 있기만 해도 치면 엉뚱한 할 일이 점수를 받는다.

    배점은 지점마다 다를 수 있어서 **사람마다 자기 지점 항목**으로 찾는다.
    """
    words = {w for w in content.split() if w and w not in _ENV_MATCH_EXCLUDE}
    if not words:
        return None
    return (
        await db.execute(
            select(EnvItem).where(EnvItem.branch_id == branch_id, EnvItem.name.in_(words))
        )
    ).scalars().first()


async def _award_todo_env(
    db: AsyncSession, todo: ProjectTodo, actor: Employee
) -> None:
    """할 일을 체크했다 — 환경정비 항목과 이름이 맞으면 수행 기록·점수를 남긴다.

    **할 일 담당자와 누른 사람 둘 다** 각자 항목 배점만큼 받는다 (2026-08-14 결정).
    담당자가 못 할 때 남이 대신 해 줄 수 있어서다. 같은 사람이면 한 번만.

    컴플레인 → `클레임해결` 과 같은 길이다 (`kindness._award_claim_resolved`).
    지점에 그 항목이 없으면 조용히 넘어간다 — 점수가 안 붙을 뿐이고 체크 자체가
    실패하면 안 된다.

    **대표·관리자는 뺀다.** `POST /env-logs` 가 그 둘을 막고 있고, 점수도
    `accrue_score` 가 안 쌓아서 기록만 남으면 환경정비 내역이 어지러워진다.
    """
    seen: set[str] = set()
    for employee_id in (todo.assignee_id, actor.id):
        if employee_id is None or employee_id in seen:
            continue
        seen.add(employee_id)
        person = await db.get(Employee, employee_id)
        if person is None or not scores_apply_to(person) or person.branch_id is None:
            continue
        item = await _env_item_for(db, person.branch_id, todo.content)
        if item is None:
            continue
        log = EnvTaskLog(
            employee_id=person.id,
            branch_id=person.branch_id,
            env_item_id=item.id,
            item_name=item.name,
            points=item.points,
            note=todo.content[:200],
            source_todo_id=todo.id,
        )
        db.add(log)
        await db.flush()
        await accrue_score(
            db,
            employee_id=person.id,
            branch_id=person.branch_id,
            category=ScoreCategory.ENV,
            points=item.points,
            created_by_id=actor.id,
            source_ref_id=log.id,
            reason=item.name,
        )


async def _retract_todo_env(db: AsyncSession, todo: ProjectTodo) -> None:
    """체크를 풀었다 — 그 할 일에서 나온 환경정비 기록과 점수를 걷는다.

    **안 걷으면 체크·해제를 반복해 점수를 무한히 쌓을 수 있다.**
    컴플레인은 '해결 완료를 못 되돌리게' 막아서 이 문제를 피했는데, 할 일은
    풀 수 있어야 하는 자리라 대신 걷는다 (프로젝트 완료 점수 회수와 같은 결).
    """
    logs = (
        (await db.execute(select(EnvTaskLog).where(EnvTaskLog.source_todo_id == todo.id)))
        .scalars()
        .all()
    )
    if not logs:
        return
    await db.execute(
        delete(ScoreEvent).where(
            ScoreEvent.category == ScoreCategory.ENV,
            ScoreEvent.source_ref_id.in_([log.id for log in logs]),
        )
    )
    for log in logs:
        await db.delete(log)


def _is_member(project: Project, current: Employee) -> bool:
    """이 프로젝트 사람인가 — **담당자와 참여 멤버뿐이다.**

    2026-08-14 정해졌다: "프로젝트 안에서 손댈 수 있는 건 그 프로젝트의
    담당자와 참여 멤버만." 역할 예외도, **만든 사람 예외도 없다.**

    **만든 사람을 안 본다**는 것이 핵심이다. 대표·관리자는 프로젝트를 만들 때
    자기가 담당자도 참여자도 아니고 **남을 지정해서** 만든다. 만든 사람을
    통과시키면 그 둘이 자기가 만든 프로젝트를 계속 손대게 된다.

    직원·점장은 만들 때 본인이 담당자로 들어가므로(앱 폼이 담당자를 반드시
    받고, 고르면 참여 멤버에도 넣는다) 자기 프로젝트에서 잠기지 않는다.

    **결재와 점수는 여기 안 건다** — 기한 연장 승인·반려와 점수 부여는
    남의 프로젝트를 판단해 주는 자리라 MASTER 전용 그대로다.
    **댓글도 안 건다** — 밖에서 물어보는 자리다 (2026-08-14 "댓글은 예외").
    """
    return project.owner_id == current.id or current.id in (
        project.assignee_ids or []
    )


def _ensure_member(project: Project, current: Employee) -> None:
    if not _is_member(project, current):
        raise HTTPException(
            403,
            detail={
                "code": "NOT_PROJECT_MEMBER",
                "message": "이 프로젝트의 담당자만 할 수 있습니다",
            },
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
    # 폼에서 같이 적은 체크리스트 — **여기서 붙인다.**
    # 앱이 만든 뒤 따로 `POST /todos` 를 부르면, 그 라우트가 이 프로젝트 사람만
    # 통과시켜서 **대표·관리자가 남에게 맡기는 프로젝트를 못 만든다.**
    for index, todo in enumerate(payload.todos):
        db.add(
            ProjectTodo(
                project_id=project.id,
                content=todo.content,
                assignee_id=todo.assignee_id,
                sort=todo.sort or index,
                created_by_id=current.id,  # NOT NULL — 빠뜨리면 만들기가 통째로 죽는다
            )
        )
    await db.flush()
    await _log_activity(db, project.id, current.id, ProjectActivityKind.CREATED, "프로젝트를 만들었어요")
    await notify_bosses(
        db, exclude=current.id, **ntext.project_created(project.title, current.name, project.id)
    )
    # 체크리스트가 붙었으면 진행률이 그걸 따라간다 (0/N → 0%).
    # `_recompute_progress` 안에서 `_settle_completion` 도 같이 돈다 —
    # 드물지만 처음부터 100% 로 만드는 경우가 거기서 정산된다.
    await _recompute_progress(db, project)
    await db.commit()
    await db.refresh(project)
    return await _single_out(db, project)


# ---------- 프로젝트 결재 요청 (연장·누락·수정·삭제 → MASTER 승인) ----------

#: 알림·타임라인에 찍히는 이름 — 종류가 넷이라 한 곳에서 만든다
_REQUEST_LABEL = {
    ProjectRequestType.EXTENSION: "기한 연장",
    ProjectRequestType.OVERDUE: "누락 사유",
    ProjectRequestType.EDIT: "프로젝트 수정",
    ProjectRequestType.DELETE: "프로젝트 삭제",
}


def _req_out(r: ProjectRequest) -> ProjectRequestOut:
    return ProjectRequestOut(
        id=r.id,
        project_id=r.project_id,
        type=r.type,
        new_due=r.new_due,
        payload=ProjectEditPayload(**r.payload) if r.payload else None,
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
    """이 프로젝트 사람이 MASTER 에게 올리는 결재 — 네 종류다.

    | 종류 | 누가 | 승인하면 |
    |---|---|---|
    | EXTENSION·OVERDUE | 담당자·참여 멤버 | 기한이 바뀐다 |
    | EDIT | **담당자만** | 이름·설명·색이 바뀐다 |
    | DELETE | **담당자만** | 프로젝트가 지워진다 |

    **여기만 아무 가드가 없었다 (2026-08-14 고침).** 프로젝트를 볼 수 있으면
    누구나 남의 프로젝트 기한을 늘려 달라고 대표에게 올릴 수 있었다.
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": "프로젝트를 찾을 수 없습니다"})
    _ensure_member(project, current)
    # 수정·삭제는 담당자만 올린다 — 예전에 직접 하던 때의 기준(`is_owner`)
    # 그대로다. 참여 멤버에게 열면 지금보다 넓어진다.
    if (
        payload.type in (ProjectRequestType.EDIT, ProjectRequestType.DELETE)
        and project.owner_id != current.id
    ):
        raise HTTPException(
            403,
            detail={"code": "NOT_PROJECT_OWNER", "message": "프로젝트 담당자만 올릴 수 있습니다"},
        )
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
        payload=payload.payload.model_dump(exclude_none=True) if payload.payload else None,
        reason=payload.reason,
        requested_by_id=current.id,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    # 승인권자(MASTER)에게 알림 (best-effort) — 승인·반려는 MASTER 전용
    label = _REQUEST_LABEL[payload.type]
    await _log_activity(db, project_id, current.id, ProjectActivityKind.DUE, f"{label} 신청")  # 승인 전 신청도 타임라인
    approvers = (await db.execute(select(Employee).where(Employee.role == Role.MASTER))).scalars().all()
    for approver in approvers:
        await notify(
            db,
            employee_id=approver.id,
            **ntext.project_request(label, project.title, current.name, project.id),
        )
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
    label = _REQUEST_LABEL[req.type]
    title = project.title if project else ""
    approved = status == ProjectRequestStatus.APPROVED

    if approved and project is not None:
        if req.type is ProjectRequestType.DELETE:
            # 타임라인을 **먼저** 남긴다 — 지우고 나면 붙일 프로젝트가 없다
            await _log_activity(db, project.id, current.id, ProjectActivityKind.DUE, f"{label} 승인")
            await _purge_project(db, project)
        elif req.type is ProjectRequestType.EDIT:
            for key, value in (req.payload or {}).items():
                setattr(project, key, value)
            await _log_activity(db, project.id, current.id, ProjectActivityKind.CREATED, f"{label} 승인")
        else:
            project.due = req.new_due  # 새 기한 반영
            project.extension_reason = req.reason
            project.overdue_notified_at = None  # 마감 변경 → 누락 알림 재무장
            await _log_activity(db, project.id, current.id, ProjectActivityKind.DUE, f"{label} 승인 — 기한 변경")
    elif not approved:
        req.reject_reason = reason
        if project is not None:  # 반려도 타임라인
            await _log_activity(db, project.id, current.id, ProjectActivityKind.DUE, f"{label} 반려")

    await notify(
        db,
        employee_id=req.requested_by_id,
        **ntext.project_request_decided(label, approved, title, reason, req.project_id),
    )
    # 삭제를 승인하면 프로젝트와 함께 이 행도 CASCADE 로 사라진다 —
    # commit 뒤에는 못 읽으므로 응답을 **미리** 만들어 둔다
    out = _req_out(req)
    await db.commit()
    if not (approved and req.type is ProjectRequestType.DELETE):
        await db.refresh(req)
        out = _req_out(req)
    return out


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


@router.post("/{project_id}/award", response_model=list[ProjectAwardOut],
             dependencies=[Depends(require_role(Role.MASTER))])
async def award_project(
    project_id: str,
    payload: ProjectAwardCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectAwardOut]:
    """프로젝트 점수 조정 — **MASTER 만**.

    완료하면 자동으로 10점이 붙는다. 그 위에서 대표가 판단해 올리거나 깎는다 —
    기한 안에 힘든 걸 해냈으면 최대 100, 완료라고만 찍고 실제로 안 했으면 -100.
    여기서 주는 값이 그 사람이 이 프로젝트에서 받는 **최종 점수**다 (더해지지 않는다).

    **`employeeId` 를 안 주면 담당자 전원에게 같은 점수를 매긴다.**
    프로젝트는 다 같이 하는 일이라 보통 이쪽을 쓴다. 한 트랜잭션이라
    중간에 실패해도 몇 명만 매겨진 상태로 남지 않는다.

    재부여하면 갱신된다. 한 번 사람이 손대면 진행률이 내려가도 회수되지 않는다.
    """
    if not payload.comment.strip():
        raise HTTPException(400, detail={"code": "REASON_REQUIRED", "message": "점수 부여 사유는 필수입니다"})
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": "프로젝트를 찾을 수 없습니다"})

    assignees = list(project.assignee_ids or [])
    if payload.employee_id is None:
        targets = assignees
        if not targets:
            raise HTTPException(400, detail={"code": "NO_ASSIGNEE", "message": "담당자가 없는 프로젝트입니다"})
    else:
        if payload.employee_id not in assignees:
            raise HTTPException(400, detail={"code": "NOT_ASSIGNEE", "message": "프로젝트 담당자가 아닙니다"})
        targets = [payload.employee_id]

    events: list[ScoreEvent] = []
    for employee_id in targets:
        employee = await db.get(Employee, employee_id)
        if employee is None:
            raise HTTPException(400, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "직원이 존재하지 않습니다"})
        # 같은 프로젝트·같은 직원은 하나만 — 재부여 시 점수·코멘트 갱신(재평가)
        existing = await db.scalar(
            select(ScoreEvent).where(
                ScoreEvent.category == ScoreCategory.PROJECT,
                ScoreEvent.source_ref_id == project_id,
                ScoreEvent.employee_id == employee_id,
            )
        )
        if existing is not None:
            existing.points = payload.points
            existing.reason = payload.comment
            existing.created_by_id = current.id
            events.append(existing)
        else:
            events.append(
                await accrue_score(
                    db,
                    employee_id=employee_id,
                    branch_id=employee.branch_id,
                    category=ScoreCategory.PROJECT,
                    points=payload.points,
                    created_by_id=current.id,
                    source_ref_id=project_id,
                    reason=payload.comment,
                )
            )
    await db.commit()
    for event in events:
        await db.refresh(event)
    return [_award_out(event) for event in events]


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
    _ensure_member(project, current)
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
    _ensure_member(project, current)
    _ensure_open(project, current)
    was_done = todo.done
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(todo, key, value)
    await db.flush()
    await _recompute_progress(db, project)  # 완료 토글 → 진행률 재계산
    if todo.done and not was_done:  # 완료로 바뀜 → 타임라인
        await _log_activity(db, project_id, current.id, ProjectActivityKind.TODO, f"완료: {todo.content}")
        # 이름이 환경정비 항목과 맞으면 그 수행도 같이 찍힌다
        await _award_todo_env(db, todo, current)
    elif was_done and not todo.done:  # 완료 취소 → 타임라인
        await _log_activity(db, project_id, current.id, ProjectActivityKind.TODO, f"완료 취소: {todo.content}")
        await _retract_todo_env(db, todo)
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
    _ensure_member(project, current)
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
    # **진행률만 직접 바꾼다 (2026-08-14).** 이름·설명·색은 MASTER 허가를 받아야
    # 해서 `POST /{id}/requests` 의 `EDIT` 로 가고, 기한은 예전부터 `EXTENSION`
    # 이 맡는다. 그래서 이 자리에 남는 것은 진행률뿐이다.
    #
    # 진행률은 보통 할 일 체크가 서버에서 다시 셈하지만(`_recompute_progress`),
    # 체크리스트가 없는 프로젝트는 여기로 직접 올린다.
    #
    # **역할로도 만든 사람으로도 통과하지 않는다.** 예전에는 MASTER·ADMIN·
    # MANAGER 가 남의 프로젝트도 제목·기한·담당자까지 다 갈 수 있었다.
    _ensure_member(project, current)
    _ensure_open(project, current)
    fields = payload.model_dump(exclude_unset=True)
    if set(fields) - {"progress"}:
        raise HTTPException(
            403,
            detail={
                "code": "NEEDS_APPROVAL",
                "message": "프로젝트 수정은 대표 승인이 필요합니다",
            },
        )
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
    # **아무도 여기로 못 지운다 (2026-08-14).** 삭제는 MASTER 허가를 받아야 한다 —
    # 담당자가 `POST /{id}/requests` 로 `DELETE` 를 올리고, 승인되면 그때 지워진다.
    # 라우트를 없애지 않는 이유는 MASTER 가 결재를 안 거치고 치울 길은 남겨야
    # 하기 때문이다 (잘못 올라온 프로젝트가 결재함에 걸려 못 지워지면 안 된다).
    if current.role != Role.MASTER:
        raise HTTPException(
            403,
            detail={
                "code": "NEEDS_APPROVAL",
                "message": "프로젝트 삭제는 대표 승인이 필요합니다",
            },
        )
    await _purge_project(db, project)
    await db.commit()
    return None


async def _purge_project(db: AsyncSession, project: Project) -> None:
    """프로젝트와 딸린 것을 다 치운다. commit 은 부르는 쪽이 한다.

    직접 삭제(MASTER)와 삭제 결재 승인이 **같은 길을 탄다** — 한쪽만 고치면
    지워진 프로젝트의 점수가 랭킹에 남는 식으로 갈린다.
    """
    # 자식(FK) 먼저 정리 — 체크리스트·기한변경요청·타임라인
    await db.execute(delete(ProjectTodo).where(ProjectTodo.project_id == project.id))
    await db.execute(delete(ProjectRequest).where(ProjectRequest.project_id == project.id))
    await db.execute(delete(ProjectActivity).where(ProjectActivity.project_id == project.id))
    # 완료 점수도 같이 지운다. `source_ref_id` 는 FK 가 아니라 그냥 두면 남는데,
    # 없어진 프로젝트 때문에 랭킹 점수가 올라가 있고 근거를 찾을 길이 없게 된다.
    await db.execute(
        delete(ScoreEvent).where(
            ScoreEvent.category == ScoreCategory.PROJECT,
            ScoreEvent.source_ref_id == project.id,
        )
    )
    await db.delete(project)
