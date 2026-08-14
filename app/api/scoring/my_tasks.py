"""내 업무 라우터 — 개인 업무 목록·체크·수정삭제 결재 (2026-08-14).

업무 화면 '환경정비' 자리가 **공통 업무 / 내 업무** 둘로 갈렸다.
공통 업무(`env.py`)는 하루에 여러 번 횟수를 더하고, 내 업무는 **하루에
한 번씩 체크**해서 다 하면 완료·남으면 누락이다.

| 누가 | 무엇 |
|---|---|
| 본인 | 목록 보기 · **추가** · 체크/해제 · 수정·삭제 **신청** |
| MASTER | 신청 **승인·반려** |

**추가만 결재가 없다.** 할 일을 늘리는 것은 스스로 하는 일이고, 고치고
지우는 것은 '안 한 일을 없던 일로 만드는' 길이라 결재를 받는다
(프로젝트 수정·삭제와 같은 이유 — backend-gap 68).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.periods import KST
from app.db.session import get_db
from app.enums import MyTaskRequestType, ProjectRequestStatus, Role
from app.models.scoring.my_task import MyTask, MyTaskCheck, MyTaskRequest
from app.models.staff.employee import Employee
from app.schemas.scoring.my_task import (
    MyTaskCreate,
    MyTaskDayOut,
    MyTaskOut,
    MyTaskRequestCreate,
    MyTaskRequestOut,
)
from app.services.notifications import notify

router = APIRouter(tags=["my-tasks"], dependencies=[Depends(get_current_user)])


def _today() -> "datetime.date":
    """KST 근무일 — 근태(`Attendance.date`)와 같은 기준이어야
    '누락 상태로 퇴근했나'를 같은 날짜로 맞출 수 있다."""
    return datetime.now(timezone.utc).astimezone(KST).date()


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "MY_TASK_NOT_FOUND", "message": "업무를 찾을 수 없습니다"})


async def _own_task(task_id: str, current: Employee, db: AsyncSession) -> MyTask:
    """**남의 업무는 없는 것처럼 다룬다** — 존재 여부도 알려주지 않는다."""
    task = await db.get(MyTask, task_id)
    if task is None or task.deleted_at is not None or task.employee_id != current.id:
        raise _not_found()
    return task


async def _pending_of(db: AsyncSession, task_ids: list[str]) -> dict[str, MyTaskRequest]:
    """업무별 대기 중인 결재 — 하나뿐이다."""
    if not task_ids:
        return {}
    rows = await db.scalars(
        select(MyTaskRequest).where(
            MyTaskRequest.my_task_id.in_(task_ids),
            MyTaskRequest.status == ProjectRequestStatus.PENDING,
        )
    )
    return {r.my_task_id: r for r in rows}


# ---------- 목록·추가 ----------
@router.get("/my-tasks", response_model=MyTaskDayOut)
async def list_my_tasks(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    # 지난 날짜를 볼 때만 준다. 안 주면 오늘 (화면이 늘 오늘이다)
    date: str | None = Query(None),
) -> MyTaskDayOut:
    """내 업무 목록 + **그날 체크 여부**를 한 번에 준다.

    목록과 체크를 따로 받으면 요청이 두 배고, 앱이 id 로 맞춰야 한다.
    """
    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, detail={"code": "INVALID_DATE", "message": "date 형식은 YYYY-MM-DD 입니다"})
    else:
        day = _today()

    tasks = list(
        await db.scalars(
            select(MyTask)
            .where(MyTask.employee_id == current.id, MyTask.deleted_at.is_(None))
            .order_by(MyTask.sort, MyTask.created_at)
        )
    )
    ids = [t.id for t in tasks]
    checked: set[str] = set()
    if ids:
        checked = set(
            await db.scalars(
                select(MyTaskCheck.my_task_id).where(
                    MyTaskCheck.my_task_id.in_(ids), MyTaskCheck.date == day
                )
            )
        )
    pending = await _pending_of(db, ids)

    out = []
    for t in tasks:
        item = MyTaskOut.model_validate(t)
        item.checked = t.id in checked
        req = pending.get(t.id)
        item.pending_request = MyTaskRequestOut.model_validate(req) if req else None
        out.append(item)

    done = len(checked)
    return MyTaskDayOut(
        date=day,
        tasks=out,
        total=len(tasks),
        done=done,
        # 항목이 하나도 없으면 완료가 아니다 — 할 일을 안 정한 것이지 다 한 게 아니다
        complete=bool(tasks) and done == len(tasks),
    )


@router.post("/my-tasks", response_model=list[MyTaskOut], status_code=201)
async def create_my_tasks(
    payload: MyTaskCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MyTaskOut]:
    """추가 — **결재 없이 본인이 한다.** 여러 개를 한 번에 받는다.

    빈 줄은 걸러 낸다 (앱에서 입력칸을 비운 채 넘어오는 경우).
    새로 만든 것은 **목록 맨 뒤**에 붙는다 — 쓰던 차례가 안 흔들린다.
    """
    contents = [c.strip() for c in payload.contents if c.strip()]
    if not contents:
        raise HTTPException(400, detail={"code": "CONTENT_REQUIRED", "message": "업무를 적어 주세요"})
    if any(len(c) > 200 for c in contents):
        raise HTTPException(400, detail={"code": "CONTENT_TOO_LONG", "message": "업무가 너무 길어요"})

    last = await db.scalar(
        select(MyTask.sort)
        .where(MyTask.employee_id == current.id, MyTask.deleted_at.is_(None))
        .order_by(MyTask.sort.desc())
        .limit(1)
    )
    base = (last or 0) + 1
    tasks = [
        MyTask(employee_id=current.id, content=c, sort=base + i)
        for i, c in enumerate(contents)
    ]
    db.add_all(tasks)
    await db.commit()
    for t in tasks:
        await db.refresh(t)
    return [MyTaskOut.model_validate(t) for t in tasks]


# ---------- 체크 ----------
@router.post("/my-tasks/{task_id}/check", status_code=204)
async def check_my_task(
    task_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """오늘 했다고 표시 — **멱등**이다 (두 번 눌러도 한 줄)."""
    task = await _own_task(task_id, current, db)
    day = _today()
    exists = await db.scalar(
        select(MyTaskCheck.id).where(MyTaskCheck.my_task_id == task.id, MyTaskCheck.date == day)
    )
    if exists is None:
        db.add(MyTaskCheck(my_task_id=task.id, employee_id=current.id, date=day))
        await db.commit()


@router.delete("/my-tasks/{task_id}/check", status_code=204)
async def uncheck_my_task(
    task_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """체크 해제 — **오늘 것만.** 지난 날짜는 되돌릴 수 없다."""
    task = await _own_task(task_id, current, db)
    row = await db.scalar(
        select(MyTaskCheck).where(MyTaskCheck.my_task_id == task.id, MyTaskCheck.date == _today())
    )
    if row is not None:
        await db.delete(row)
        await db.commit()


# ---------- 수정·삭제 결재 ----------
@router.post("/my-tasks/{task_id}/requests", response_model=MyTaskRequestOut, status_code=201)
async def create_my_task_request(
    task_id: str,
    payload: MyTaskRequestCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTaskRequestOut:
    """수정·삭제 신청 — MASTER 가 승인해야 실제로 바뀐다.

    **신청할 때 항목을 안 건드린다.** 미리 고쳐 두고 되돌리는 식이면
    승인 전인데 이미 바뀐 내용이 화면에 뜬다.
    """
    task = await _own_task(task_id, current, db)
    if payload.type == MyTaskRequestType.EDIT:
        content = (payload.payload or {}).get("content", "").strip()
        if not content:
            raise HTTPException(400, detail={"code": "CONTENT_REQUIRED", "message": "고칠 내용을 적어 주세요"})

    # 업무 하나에 대기 요청은 하나뿐 — 수정 대기 중에 삭제까지 오면
    # 처리 순서에 따라 결과가 갈린다
    dup = await db.scalar(
        select(MyTaskRequest.id).where(
            MyTaskRequest.my_task_id == task.id,
            MyTaskRequest.status == ProjectRequestStatus.PENDING,
        )
    )
    if dup is not None:
        raise HTTPException(400, detail={"code": "ALREADY_PENDING", "message": "이미 결재를 기다리는 업무입니다"})

    req = MyTaskRequest(
        my_task_id=task.id,
        type=payload.type,
        payload=payload.payload if payload.type == MyTaskRequestType.EDIT else None,
        reason=payload.reason,
        requested_by_id=current.id,
    )
    db.add(req)
    await db.flush()
    label = "수정" if payload.type == MyTaskRequestType.EDIT else "삭제"
    for eid in await _master_ids(db):
        await notify(
            db,
            employee_id=eid,
            type="MY_TASK",
            title=f"내 업무 {label} 결재",
            body=f"{current.name} · {task.content}",
            link="/work",
        )
    await db.commit()
    await db.refresh(req)
    return MyTaskRequestOut.model_validate(req)


async def _master_ids(db: AsyncSession) -> list[str]:
    """**MASTER 만** — 이 결재는 대표 전용이다 (2026-08-14 정책)."""
    return list(
        await db.scalars(
            select(Employee.id).where(Employee.role == Role.MASTER, Employee.deleted_at.is_(None))
        )
    )


@router.get("/my-task-requests", response_model=list[MyTaskRequestOut])
async def list_my_task_requests(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: ProjectRequestStatus | None = Query(None),
) -> list[MyTaskRequestOut]:
    """MASTER 는 전원 것, 그 밖은 **본인이 올린 것만**."""
    stmt = select(MyTaskRequest).order_by(MyTaskRequest.created_at.desc())
    if current.role != Role.MASTER:
        stmt = stmt.where(MyTaskRequest.requested_by_id == current.id)
    if status:
        stmt = stmt.where(MyTaskRequest.status == status)
    rows = list(await db.scalars(stmt))
    return await _decorate(db, rows)


async def _decorate(db: AsyncSession, rows: list[MyTaskRequest]) -> list[MyTaskRequestOut]:
    """이름·업무 내용을 붙인다 — 결재 화면이 '누가 무엇을' 을 그려야 한다."""
    out = []
    names: dict[str, str] = {}
    contents: dict[str, str] = {}
    for r in rows:
        if r.requested_by_id not in names:
            emp = await db.get(Employee, r.requested_by_id)
            names[r.requested_by_id] = emp.name if emp else ""
        if r.my_task_id not in contents:
            task = await db.get(MyTask, r.my_task_id)
            contents[r.my_task_id] = task.content if task else ""
        item = MyTaskRequestOut.model_validate(r)
        item.requester_name = names[r.requested_by_id]
        item.task_content = contents[r.my_task_id]
        out.append(item)
    return out


async def _decide(
    request_id: str,
    approve: bool,
    reason: str | None,
    current: Employee,
    db: AsyncSession,
) -> MyTaskRequest:
    req = await db.get(MyTaskRequest, request_id)
    if req is None:
        raise HTTPException(404, detail={"code": "REQUEST_NOT_FOUND", "message": "결재를 찾을 수 없습니다"})
    if req.status != ProjectRequestStatus.PENDING:
        raise HTTPException(400, detail={"code": "ALREADY_DONE", "message": "이미 처리된 결재입니다"})

    task = await db.get(MyTask, req.my_task_id)
    if approve and task is not None:
        if req.type == MyTaskRequestType.EDIT:
            task.content = (req.payload or {}).get("content", task.content)
        else:
            # **행을 안 지운다.** 지우면 CASCADE 로 체크 기록까지 사라져서
            # 지난 날짜가 '하지도 않은 일을 한 것'으로 보인다
            task.deleted_at = datetime.now(timezone.utc)

    req.status = ProjectRequestStatus.APPROVED if approve else ProjectRequestStatus.REJECTED
    req.decided_by_id = current.id
    req.decided_at = datetime.now(timezone.utc)
    if not approve:
        req.reject_reason = reason
    label = "수정" if req.type == MyTaskRequestType.EDIT else "삭제"
    await notify(
        db,
        employee_id=req.requested_by_id,
        type="MY_TASK",
        title=f"내 업무 {label} {'승인' if approve else '반려'}",
        body=(task.content if task else "") + (f" · {reason}" if not approve and reason else ""),
        link="/work",
    )
    await db.commit()
    await db.refresh(req)
    return req


@router.post(
    "/my-task-requests/{request_id}/approve",
    response_model=MyTaskRequestOut,
    dependencies=[Depends(require_role(Role.MASTER))],  # 승인·반려는 대표만
)
async def approve_my_task_request(
    request_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTaskRequestOut:
    req = await _decide(request_id, True, None, current, db)
    return (await _decorate(db, [req]))[0]


@router.post(
    "/my-task-requests/{request_id}/reject",
    response_model=MyTaskRequestOut,
    dependencies=[Depends(require_role(Role.MASTER))],
)
async def reject_my_task_request(
    request_id: str,
    reason: str = Query(..., min_length=1),  # 반려는 사유가 있어야 뭘 고칠지 안다
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTaskRequestOut:
    req = await _decide(request_id, False, reason, current, db)
    return (await _decorate(db, [req]))[0]
