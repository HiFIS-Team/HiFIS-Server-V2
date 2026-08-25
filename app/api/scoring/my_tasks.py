"""내 업무 라우터 — 개인 업무 목록·체크·수정삭제 결재 (2026-08-14).

업무 화면 '환경정비' 자리가 **공통 업무 / 내 업무** 둘로 갈렸다.
공통 업무(`env.py`)는 하루에 여러 번 횟수를 더하고, 내 업무는 **하루에
한 번씩 체크**해서 다 하면 완료·남으면 누락이다.

| 누가 | 무엇 |
|---|---|
| 본인 | 목록 보기 · **추가** · 체크 · 수정·삭제 (아직 안 한 것) · 수정·삭제 **신청** |
| MASTER | 신청 **승인·반려** |

**체크가 경계다 (2026-08-20 요청).** 한 번이라도 체크한 업무는 그 뒤로
계속 결재를 받아야 하고, 아직 한 번도 안 한 업무는 결재 없이 바로 고치고
지운다 — 프로젝트 할 일과 같은 규칙이다.

```
만든 직후            수정·삭제 바로  (아무 기록이 없다)
  └ 한 번 체크 →    수정·삭제 결재  (되돌릴 수 없다)
```

**체크는 되돌릴 수 없다.** 해제를 열어 두면 '고치기 전에 풀면 그만'이라
결재가 뜻을 잃는다. 그래서 앱이 누르기 전에 한 번 묻는다.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_filter, get_current_user, require_role
from app.core.periods import KST
from app.db.session import get_db
from app.enums import EmployeeStatus, MyTaskRequestType, ProjectRequestStatus, Role
from app.models.scoring.my_task import MyTask, MyTaskCheck, MyTaskMiss, MyTaskRequest
from app.models.scoring.score_event import ScoreEvent
from app.models.staff.employee import Employee
from app.schemas.scoring.my_task import (
    EVERY_DAY,
    MyTaskCreate,
    MyTaskDayOut,
    MyTaskExcuseCreate,
    MyTaskMissOut,
    MyTaskOut,
    MyTaskRequestCreate,
    MyTaskRequestOut,
    MyTaskRosterRow,
    MyTaskUpdate,
    clean_weekdays,
)
from app.services import notification_texts as ntext
from app.services.my_tasks import due_tasks
from app.services.notifications import master_ids, notify

router = APIRouter(tags=["my-tasks"], dependencies=[Depends(get_current_user)])


def _today() -> "datetime.date":
    """KST 근무일 — 근태(`Attendance.date`)와 같은 기준이어야
    '누락 상태로 퇴근했나'를 같은 날짜로 맞출 수 있다."""
    return datetime.now(timezone.utc).astimezone(KST).date()


def _parse_date(date: str | None) -> "datetime.date":
    """안 주면 오늘 — 화면이 늘 오늘이라 대개 비어 온다."""
    if not date:
        return _today()
    try:
        return datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, detail={"code": "INVALID_DATE", "message": "date 형식은 YYYY-MM-DD 입니다"})


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "MY_TASK_NOT_FOUND", "message": "업무를 찾을 수 없습니다"})


async def _own_task(task_id: str, current: Employee, db: AsyncSession) -> MyTask:
    """**남의 업무는 없는 것처럼 다룬다** — 존재 여부도 알려주지 않는다."""
    task = await db.get(MyTask, task_id)
    if task is None or task.deleted_at is not None or task.employee_id != current.id:
        raise _not_found()
    return task


async def _reject_duplicate(
    db: AsyncSession,
    employee_id: str,
    contents: list[str],
    *,
    skip_id: str | None = None,
) -> None:
    """이미 있는 업무와 이름이 같으면 막는다.

    **똑같은 줄이 둘이면 손쓸 방법이 없다.** 어느 쪽을 체크했는지 알 수 없고,
    하나를 지워도 남은 쪽이 그대로라 **'삭제가 안 됐다'로 보인다.**

    운영에서 실제로 겪었다 (2026-08-15) — 한 사람의 목록에 `알바몬체크` 가
    두 줄이 됐다. 추가할 때가 아니라 **수정 결재로** 생겼다: 다른 줄의 내용을
    이미 있는 이름으로 고쳐 달라고 올렸고, 승인되면서 둘이 같아졌다.
    그래서 추가뿐 아니라 **수정 신청도 같이 막는다.**

    [skip_id] 는 수정 신청이 자기 자신과 비교되지 않게 뺄 때 쓴다.
    """
    stmt = select(MyTask.content).where(
        MyTask.employee_id == employee_id, MyTask.deleted_at.is_(None)
    )
    if skip_id:
        stmt = stmt.where(MyTask.id != skip_id)
    existing = set(await db.scalars(stmt))
    dup = next((c for c in contents if c in existing), None)
    if dup is not None:
        raise HTTPException(
            400,
            detail={"code": "DUPLICATE_CONTENT", "message": f"이미 있는 업무예요 — {dup}"},
        )


async def _checked_ever(db: AsyncSession, task_ids: list[str]) -> set[str]:
    """**날짜를 안 가리고** 체크 기록이 한 줄이라도 있는 업무들 (2026-08-20).

    오늘 체크했나(`MyTaskCheck.date == day`)와 다른 값이다 — 이건 통틀어서다.
    한 번이라도 한 업무는 그 뒤로 수정·삭제가 결재를 탄다.
    """
    if not task_ids:
        return set()
    return set(
        await db.scalars(
            select(MyTaskCheck.my_task_id).where(MyTaskCheck.my_task_id.in_(task_ids)).distinct()
        )
    )


async def _require_open(db: AsyncSession, task: MyTask) -> None:
    """결재 없이 바로 고칠 수 있는 상태인가 — 아니면 400.

    막는 자리가 둘이다.

    | | 왜 |
    |---|---|
    | 한 번이라도 체크함 | 한 일을 없던 일로 만드는 길이 된다 — 결재를 받는다 |
    | 결재를 기다리는 중 | 대기 중인 신청과 바로 고친 것이 어긋난다 |
    """
    if await _checked_ever(db, [task.id]):
        raise HTTPException(
            400,
            detail={
                "code": "TASK_LOCKED",
                "message": "이미 체크한 업무예요 — 수정·삭제는 결재를 받아야 해요",
            },
        )
    dup = await db.scalar(
        select(MyTaskRequest.id).where(
            MyTaskRequest.my_task_id == task.id,
            MyTaskRequest.status == ProjectRequestStatus.PENDING,
        )
    )
    if dup is not None:
        raise HTTPException(400, detail={"code": "ALREADY_PENDING", "message": "이미 결재를 기다리는 업무입니다"})


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
    # 남의 것 — **MASTER·ADMIN 만.** 그 밖에는 넣어도 본인 것이 온다
    employee_id: str | None = Query(None, alias="employeeId"),
) -> MyTaskDayOut:
    """내 업무 목록 + **그날 체크 여부**를 한 번에 준다.

    목록과 체크를 따로 받으면 요청이 두 배고, 앱이 id 로 맞춰야 한다.

    대표·관리자는 `employeeId` 로 **남의 것을 본다** (읽기만 — 체크·수정은
    본인만 한다). 그 밖에는 403 이 아니라 **조용히 본인 것**으로 고정한다
    (`/attendance` 와 같은 규칙 — backend-gap 60).
    """
    target_id = current.id
    if employee_id and current.role in (Role.MASTER, Role.ADMIN, Role.MANAGER):
        target_id = employee_id
    day = _parse_date(date)
    owner = await db.get(Employee, target_id)
    if owner is None:
        raise _not_found()

    # **요일 필터·이월 판정은 서비스가 한다** — 대표 판·퇴근 알림과 같은
    # 규칙이어야 한다 (`app/services/my_tasks.py`)
    due = (await due_tasks(db, [owner], day, today=_today()))[owner.id]
    ids = [d.task.id for d in due.tasks]
    pending = await _pending_of(db, ids)
    # **오늘 체크와 따로 센다** — 앱이 수정·삭제를 바로 보낼지 결재로 보낼지
    # 이 값으로 가른다 (2026-08-20)
    ever = await _checked_ever(db, ids)

    out = []
    for d in due.tasks:
        item = MyTaskOut.model_validate(d.task)
        item.checked = d.task.id in due.checked
        item.ever_checked = d.task.id in ever
        item.carried_from = d.carried_from
        req = pending.get(d.task.id)
        item.pending_request = MyTaskRequestOut.model_validate(req) if req else None
        out.append(item)

    return MyTaskDayOut(
        date=day,
        tasks=out,
        total=due.total,
        done=due.done,
        complete=due.complete,
    )


@router.get(
    "/my-tasks/roster",
    response_model=list[MyTaskRosterRow],
    dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))],  # MASTER 자동 승계
)
async def my_task_roster(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_filter),
    date: str | None = Query(None),
) -> list[MyTaskRosterRow]:
    """오늘 누가 몇 개 중 몇 개를 했나 — **한 번에** 준다.

    사람마다 `/my-tasks?employeeId=` 를 부르면 인원수만큼 요청이 나간다.
    전사 근태 달력(`/attendance/calendar/all`)과 같은 판단이다.

    **MASTER·ADMIN 은 세지 않는다.** 그들에게는 내 업무 화면이 없어서 늘 0개다.
    업무를 하나도 안 만든 사람도 목록에는 선다 — 안 정했다는 것도 봐야 한다.
    """
    day = _parse_date(date)
    stmt = select(Employee).where(
        Employee.role.notin_([Role.MASTER, Role.ADMIN]),
        Employee.status == EmployeeStatus.ACTIVE,
        Employee.deleted_at.is_(None),
    )
    if scope:
        stmt = stmt.where(Employee.branch_id == scope)
    people = list(await db.scalars(stmt.order_by(Employee.name)))
    if not people:
        return []

    # 하루 목록과 **같은 셈**이다 — 요일·이월·월차까지 서비스 한 곳에서 판단한다.
    # 여기만 다르면 대표 화면의 `3/5` 와 본인 화면의 `3/3` 이 갈린다
    due = await due_tasks(db, people, day, today=_today())
    return [
        MyTaskRosterRow(
            employee_id=p.id,
            name=p.name,
            total=due[p.id].total,
            done=due[p.id].done,
            complete=due[p.id].complete,
        )
        for p in people
    ]


@router.post("/my-tasks", response_model=list[MyTaskOut], status_code=201)
async def create_my_tasks(
    payload: MyTaskCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MyTaskOut]:
    """추가 — **결재 없이 본인이 한다.** 여러 개를 한 번에 받는다.

    빈 줄은 걸러 낸다 (앱에서 입력칸을 비운 채 넘어오는 경우).
    새로 만든 것은 **목록 맨 뒤**에 붙는다 — 쓰던 차례가 안 흔들린다.

    **같은 내용을 두 줄로 만들지 않는다** (아래 [_reject_duplicate] 참고).
    """
    # 한 번에 올린 것들끼리 겹치면 **요일을 합친다** — 요일을 하나씩 훑으며
    # 담는 화면에서 같은 업무가 여러 요일에 걸리면 같은 이름이 여러 번 온다.
    # 두 줄로 만들면 어느 쪽을 체크했는지 알 수 없다 (`_reject_duplicate` 참고)
    merged: dict[str, set[int]] = {}
    for content, days in payload.rows():
        content = content.strip()
        if not content:
            continue
        if len(content) > 200:
            raise HTTPException(400, detail={"code": "CONTENT_TOO_LONG", "message": "업무가 너무 길어요"})
        merged.setdefault(content, set()).update(days)
    if not merged:
        raise HTTPException(400, detail={"code": "CONTENT_REQUIRED", "message": "업무를 적어 주세요"})

    await _reject_duplicate(db, current.id, list(merged))

    last = await db.scalar(
        select(MyTask.sort)
        .where(MyTask.employee_id == current.id, MyTask.deleted_at.is_(None))
        .order_by(MyTask.sort.desc())
        .limit(1)
    )
    base = (last or 0) + 1
    # `dict` 라 적은 차례가 그대로 간다
    tasks = [
        MyTask(
            employee_id=current.id,
            content=content,
            weekdays=sorted(days),
            sort=base + i,
        )
        for i, (content, days) in enumerate(merged.items())
    ]
    db.add_all(tasks)
    await db.commit()
    for t in tasks:
        await db.refresh(t)
    return [MyTaskOut.model_validate(t) for t in tasks]


# ---------- 아직 한 번도 안 한 업무 — 결재 없이 바로 ----------
@router.patch("/my-tasks/{task_id}", response_model=MyTaskOut)
async def update_my_task(
    task_id: str,
    payload: MyTaskUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTaskOut:
    """수정 — **한 번도 체크한 적 없을 때만** (2026-08-20 요청).

    잘못 적은 것을 고치는 자리다. 아무 기록이 없으므로 없앨 것도 없다.
    한 번이라도 체크했으면 `400 TASK_LOCKED` — 그때는 결재를 올린다.
    """
    task = await _own_task(task_id, current, db)
    await _require_open(db, task)

    content = (payload.content or "").strip() or task.content
    if len(content) > 200:
        raise HTTPException(400, detail={"code": "CONTENT_TOO_LONG", "message": "업무가 너무 길어요"})
    days = clean_weekdays(payload.weekdays) if payload.weekdays is not None else list(task.weekdays or EVERY_DAY)
    if content == task.content and days == sorted(task.weekdays or []):
        raise HTTPException(400, detail={"code": "SAME_CONTENT", "message": "바뀐 것이 없어요"})
    if content != task.content:
        # 결재로 겪었던 그 자리다 — 같은 이름 두 줄은 손쓸 방법이 없다
        await _reject_duplicate(db, current.id, [content], skip_id=task.id)

    task.content = content
    task.weekdays = days
    await db.commit()
    await db.refresh(task)
    return MyTaskOut.model_validate(task)


@router.delete("/my-tasks/{task_id}", status_code=204)
async def delete_my_task(
    task_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """삭제 — **한 번도 체크한 적 없을 때만** (2026-08-20 요청).

    결재로 지울 때와 같이 **행은 남긴다** (`deleted_at`). 체크 기록이 없어서
    지워도 잃을 것은 없지만, 지우는 길이 둘로 갈리면 나중에 되짚기 어렵다.
    """
    task = await _own_task(task_id, current, db)
    await _require_open(db, task)
    task.deleted_at = datetime.now(timezone.utc)
    await db.commit()


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
    """**체크는 되돌릴 수 없다 (2026-08-20 요청).** 늘 400 이다.

    해제를 열어 두면 결재가 뜻을 잃는다 — 고치고 싶을 때 체크를 풀고
    '아직 안 한 업무'로 되돌린 뒤 바로 고치면 그만이기 때문이다.

    **라우트를 안 지운다.** 지우면 옛 앱(해제 버튼이 있던 빌드)이 404 를
    받아 '업무를 찾을 수 없습니다'로 뜬다 — 왜 안 되는지가 안 보인다.
    """
    await _own_task(task_id, current, db)  # 남의 업무는 없는 것처럼
    raise HTTPException(
        400,
        detail={"code": "CHECK_FINAL", "message": "체크는 되돌릴 수 없어요"},
    )


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

    아직 한 번도 체크 안 한 업무는 앱이 여기로 안 오고 `PATCH`·`DELETE` 로
    바로 간다. 그래도 **여기를 막지 않는다** — 옛 앱은 이 길밖에 몰라서,
    막으면 그 빌드에서 수정 자체가 안 된다. 결과는 어느 쪽이든 같다.
    """
    task = await _own_task(task_id, current, db)
    if payload.type == MyTaskRequestType.EDIT:
        raw = payload.payload or {}
        # **내용·요일 중 하나만 고쳐도 된다 (2026-08-20).** 안 보낸 칸은 지금
        # 값을 그대로 실어서, 승인하는 쪽이 최종 모습을 그대로 본다
        content = str(raw.get("content") or "").strip() or task.content
        days = (
            clean_weekdays(raw.get("weekdays"))
            if "weekdays" in raw
            else list(task.weekdays or EVERY_DAY)
        )
        if not content:
            raise HTTPException(400, detail={"code": "CONTENT_REQUIRED", "message": "고칠 내용을 적어 주세요"})
        if content == task.content and days == sorted(task.weekdays or []):
            raise HTTPException(400, detail={"code": "SAME_CONTENT", "message": "바뀐 것이 없어요"})
        if content != task.content:
            # 승인되고 나서야 겹치는 걸 알면 이미 두 줄이다 — 올릴 때 막는다
            await _reject_duplicate(db, current.id, [content], skip_id=task.id)
        payload.payload = {"content": content, "weekdays": days}

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
    for eid in await master_ids(db, exclude=current.id):
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
            body = req.payload or {}
            task.content = body.get("content", task.content)
            # 요일도 같이 실려 온다 (2026-08-20). 옛 결재는 이 칸이 없어서
            # 그대로 둔다 — 그때는 매일이 전제였다
            if body.get("weekdays"):
                task.weekdays = clean_weekdays(body["weekdays"])
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


# ---------- 확정 누락 · 사유서 (2026-08-21) ----------
#
# 수정·삭제 결재와 **같은 자리**에 둔다 (대표 결정). 문서가 다른 화면으로
# 흩어지면 결재하는 사람이 두 군데를 봐야 한다.
#
# ```
# 누락 확정  →  점수 -20 먼저 깎임  →  사유서  →  승인이면 **회복**
#                                              반려면 그대로
# ```


async def _decorate_misses(db: AsyncSession, rows: list[MyTaskMiss]) -> list[MyTaskMissOut]:
    """이름을 붙인다 — 결재 화면이 '누가' 를 그려야 한다."""
    names: dict[str, str] = {}
    out = []
    for r in rows:
        if r.employee_id not in names:
            emp = await db.get(Employee, r.employee_id)
            names[r.employee_id] = emp.name if emp else ""
        item = MyTaskMissOut.model_validate(r)
        item.employee_name = names[r.employee_id]
        out.append(item)
    return out


@router.get("/my-task-misses", response_model=list[MyTaskMissOut])
async def list_my_task_misses(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    # camelCase 로 받는다 — 앱이 보내는 이름이다 (`/my-tasks` 와 같은 규칙)
    employee_id: str | None = Query(None, alias="employeeId"),
    since: str | None = Query(None, description="이 날짜부터 (YYYY-MM-DD)"),
) -> list[MyTaskMissOut]:
    """확정 누락 목록 — **MEMBER 는 본인 것만.**

    남의 누락은 근태 시각과 같은 종류의 값이라 아무나 보면 안 된다
    (backend-gap 60). 점장은 자기 지점 것을 본다 — 그 지점 누락으로
    본인 기본급이 깎이므로 무엇 때문인지 볼 수 있어야 한다.
    """
    stmt = select(MyTaskMiss).order_by(MyTaskMiss.date.desc())
    if current.role == Role.MEMBER:
        stmt = stmt.where(MyTaskMiss.employee_id == current.id)
    else:
        if current.role == Role.MANAGER:
            stmt = stmt.where(MyTaskMiss.branch_id == current.branch_id)
        if employee_id:
            stmt = stmt.where(MyTaskMiss.employee_id == employee_id)
    if since:
        stmt = stmt.where(MyTaskMiss.date >= _parse_date(since))
    return await _decorate_misses(db, list(await db.scalars(stmt)))


@router.post("/my-task-misses/{miss_id}/excuse", response_model=MyTaskMissOut)
async def submit_my_task_excuse(
    miss_id: str,
    payload: MyTaskExcuseCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTaskMissOut:
    """누락 사유서를 낸다 — **본인만.**

    **반려된 것은 다시 낼 수 있다.** 한 번 반려로 영영 닫으면 잘못 적은
    사유를 바로잡을 길이 없다. 대기 중인 것만 막는다.
    """
    miss = await db.get(MyTaskMiss, miss_id)
    if miss is None or miss.employee_id != current.id:
        raise HTTPException(404, detail={"code": "MISS_NOT_FOUND", "message": "누락 기록을 찾을 수 없습니다"})
    if miss.excuse_status == ProjectRequestStatus.PENDING:
        raise HTTPException(400, detail={"code": "ALREADY_PENDING", "message": "이미 결재를 기다리는 사유서입니다"})
    if miss.excused:
        raise HTTPException(400, detail={"code": "ALREADY_EXCUSED", "message": "이미 회복된 누락입니다"})

    miss.excuse_reason = payload.reason
    miss.excuse_status = ProjectRequestStatus.PENDING
    # 다시 낸 것이면 지난 결재 흔적을 지운다 — 안 지우면 '반려됐는데 대기'가 된다
    miss.decided_by_id = None
    miss.decided_at = None
    miss.reject_reason = None
    for eid in await master_ids(db, exclude=current.id):
        await notify(db, employee_id=eid, **ntext.task_miss_excuse(current.name, miss.date))
    await db.commit()
    await db.refresh(miss)
    return (await _decorate_misses(db, [miss]))[0]


async def _decide_miss(
    miss_id: str,
    approve: bool,
    reason: str | None,
    current: Employee,
    db: AsyncSession,
) -> MyTaskMiss:
    """승인이면 **회복** — 깎았던 점수 줄을 지운다.

    상쇄로 +20 을 한 줄 더 넣지 않는다. 원장 합은 같지만 랭킹 내역에
    `업무 누락 -20` 과 `업무 누락 +20` 이 나란히 서서 무슨 일인지 알 수 없다.
    무슨 일이 있었는지는 이 표(`my_task_misses`)가 들고 있다.
    """
    miss = await db.get(MyTaskMiss, miss_id)
    if miss is None:
        raise HTTPException(404, detail={"code": "MISS_NOT_FOUND", "message": "누락 기록을 찾을 수 없습니다"})
    if miss.excuse_status != ProjectRequestStatus.PENDING:
        raise HTTPException(400, detail={"code": "ALREADY_DONE", "message": "이미 처리된 사유서입니다"})

    miss.excuse_status = ProjectRequestStatus.APPROVED if approve else ProjectRequestStatus.REJECTED
    miss.decided_by_id = current.id
    miss.decided_at = datetime.now(timezone.utc)
    if approve:
        if miss.score_event_id:
            event = await db.get(ScoreEvent, miss.score_event_id)
            if event is not None:
                await db.delete(event)
            miss.score_event_id = None
    else:
        miss.reject_reason = reason
    await notify(
        db,
        employee_id=miss.employee_id,
        **ntext.task_miss_decided(miss.date, approve, reason),
    )
    await db.commit()
    await db.refresh(miss)
    return miss


@router.post(
    "/my-task-misses/{miss_id}/approve",
    response_model=MyTaskMissOut,
    dependencies=[Depends(require_role(Role.MASTER))],  # 수정·삭제 결재와 같은 자리다
)
async def approve_my_task_excuse(
    miss_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTaskMissOut:
    miss = await _decide_miss(miss_id, True, None, current, db)
    return (await _decorate_misses(db, [miss]))[0]


@router.post(
    "/my-task-misses/{miss_id}/reject",
    response_model=MyTaskMissOut,
    dependencies=[Depends(require_role(Role.MASTER))],
)
async def reject_my_task_excuse(
    miss_id: str,
    reason: str = Query(..., min_length=1),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTaskMissOut:
    miss = await _decide_miss(miss_id, False, reason, current, db)
    return (await _decorate_misses(db, [miss]))[0]
