"""WorkoutLog 라우터 — 운동일지 (CLAUDE.md §3.4).

읽기는 그 회원을 볼 수 있는 직원이면 된다(지점 스코프). **쓰기는 담당
트레이너와 점장·관리자만** — 남의 회원 일지를 아무나 고치면 PT 회차가
어긋난다.
"""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user
from app.core.storage import save_workout_media
from app.db.session import get_db
from app.enums import Role, WorkoutKind
from app.models.members.member import Member
from app.models.members.registration import Registration
from app.models.members.workout import WorkoutLog
from app.models.staff.employee import Employee
from app.schemas.members.workout import (
    WorkoutLogCreate,
    WorkoutLogOut,
    WorkoutLogUpdate,
    WorkoutMediaOut,
)

router = APIRouter(prefix="/workouts", tags=["workouts"], dependencies=[Depends(get_current_user)])


def _member_not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "MEMBER_NOT_FOUND", "message": "회원을 찾을 수 없습니다"})


async def _visible_member(db: AsyncSession, member_id: str, scope: str | None) -> Member:
    """볼 수 있는 회원만 돌려준다 — 남의 지점 회원은 있다는 사실도 숨긴다(404)."""
    member = await db.get(Member, member_id)
    if member is None or (scope and member.branch_id != scope):
        raise _member_not_found()
    return member


def _ensure_can_write(member: Member, current: Employee) -> None:
    if current.role in (Role.MASTER, Role.ADMIN, Role.MANAGER):
        return
    if member.owner_trainer_id == current.id:
        return
    raise HTTPException(
        403, detail={"code": "NOT_MY_MEMBER", "message": "담당 트레이너만 일지를 쓸 수 있습니다"}
    )


async def _paid_sessions(db: AsyncSession, member_id: str) -> int:
    """회원이 결제한 총 회차 — 등록권 전부를 더한 값(재등록하면 늘어난다)."""
    total = await db.scalar(
        select(func.coalesce(func.sum(Registration.total_sessions), 0)).where(
            Registration.member_id == member_id
        )
    )
    return int(total or 0)


@router.get("", response_model=list[WorkoutLogOut])
async def list_workouts(
    member_id: str = Query(..., alias="memberId"),
    kind: WorkoutKind | None = Query(None),
    scope: str | None = Depends(branch_scope),
    db: AsyncSession = Depends(get_db),
) -> list[WorkoutLog]:
    await _visible_member(db, member_id, scope)
    stmt = select(WorkoutLog).where(WorkoutLog.member_id == member_id)
    if kind is not None:
        stmt = stmt.where(WorkoutLog.kind == kind)
    # PT 는 회차 순, 개인 운동은 한 날 여러 개일 수 있어 만든 순서로 갈린다
    result = await db.execute(
        stmt.order_by(
            WorkoutLog.performed_on.desc(),
            WorkoutLog.session_no.desc().nulls_last(),
            WorkoutLog.created_at.desc(),
        )
    )
    return list(result.scalars().all())


@router.post("/media", response_model=WorkoutMediaOut, status_code=201)
async def upload_workout_media(
    file: UploadFile = File(...),
    current: Employee = Depends(get_current_user),
) -> WorkoutMediaOut:
    """자료 올리기 — 돌려받은 주소를 일지의 `media` 묶음에 실어 보낸다.

    **일지 저장과 나뉘어 있다.** 일지는 JSON 인데 파일을 실으려면 multipart 로
    바꿔야 하고, 그러면 표까지 전부 폼 필드로 풀어야 한다.
    """
    url, kind = await save_workout_media(file)
    return WorkoutMediaOut(url=url, kind=kind)


@router.post("", response_model=WorkoutLogOut, status_code=201)
async def create_workout(
    payload: WorkoutLogCreate,
    current: Employee = Depends(get_current_user),
    scope: str | None = Depends(branch_scope),
    db: AsyncSession = Depends(get_db),
) -> WorkoutLog:
    member = await _visible_member(db, payload.member_id, scope)
    _ensure_can_write(member, current)

    session_no: int | None = None
    if payload.kind is WorkoutKind.PT:
        paid = await _paid_sessions(db, member.id)
        if paid == 0:
            raise HTTPException(
                400,
                detail={"code": "NO_REGISTRATION", "message": "등록권이 있어야 PT 일지를 쓸 수 있습니다"},
            )
        # 안 주면 다음 회차를 서버가 매긴다 — 앱 두 대가 동시에 눌러도 겹치지 않게
        session_no = payload.session_no or await _next_session_no(db, member.id)
        if session_no > paid:
            raise HTTPException(
                400,
                detail={
                    "code": "SESSIONS_EXHAUSTED",
                    "message": f"결제한 {paid}회를 모두 썼습니다. 재등록하면 이어서 쓸 수 있어요",
                },
            )
        taken = await db.scalar(
            select(func.count())
            .select_from(WorkoutLog)
            .where(
                WorkoutLog.member_id == member.id,
                WorkoutLog.kind == WorkoutKind.PT,
                WorkoutLog.session_no == session_no,
            )
        )
        if taken:
            raise HTTPException(
                400,
                detail={"code": "SESSION_TAKEN", "message": f"{session_no}회차 일지가 이미 있습니다"},
            )

    log = WorkoutLog(
        member_id=member.id,
        kind=payload.kind,
        session_no=session_no,
        title=payload.title.strip(),
        performed_on=payload.performed_on,
        author_id=current.id,
        weights=[row.model_dump() for row in payload.weights],
        cardio=[row.model_dump() for row in payload.cardio],
        media=[group.model_dump() for group in payload.media],
        trainer_feedback=payload.trainer_feedback,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def _next_session_no(db: AsyncSession, member_id: str) -> int:
    """이번에 쓸 PT 일지 회차 — **이미 받은 싸인과 이미 쓴 일지 중 큰 쪽 다음**.

    일지 번호만 보면 **일지가 생기기 전부터 있던 회원이 통째로 막힌다.**
    14회를 이미 받은 회원은 일지가 0장이라 여기서 1을 주는데, 싸인을 찍을 때는
    `_require_workout` 이 누적 회차 다음인 **15회차** 일지를 찾는다. 그래서
    일지를 써도 싸인이 안 열리고, 2·3회차를 더 써도 영영 안 맞는다
    (2026-08-31 대표가 짚었다 — 운영 회원 전부가 이 상태다).

    | | 누적 싸인 | 일지 최대 | 이번 회차 |
    |---|---|---|---|
    | 옛 회원 (일지 없음) | 14 | 0 | **15** |
    | 평소 (싸인까지 끝남) | 7 | 7 | 8 |
    | 미리 써 둔 경우 | 6 | 7 | 8 |

    **재등록은 안 가른다.** 싸인은 등록권마다 1 부터 다시 세지만(남은 회차를
    세는 값이라 그게 맞다) 일지는 회원 평생 번호라 이어진다. 그 사이는
    `_require_workout` 이 옮겨 담는다.
    """
    signed = await db.scalar(
        select(func.coalesce(func.sum(Registration.used_sessions), 0)).where(
            Registration.member_id == member_id
        )
    )
    written = await db.scalar(
        select(func.coalesce(func.max(WorkoutLog.session_no), 0)).where(
            WorkoutLog.member_id == member_id, WorkoutLog.kind == WorkoutKind.PT
        )
    )
    return max(int(signed or 0), int(written or 0)) + 1


@router.get("/{workout_id}", response_model=WorkoutLogOut)
async def get_workout(
    workout_id: str,
    scope: str | None = Depends(branch_scope),
    db: AsyncSession = Depends(get_db),
) -> WorkoutLog:
    log = await db.get(WorkoutLog, workout_id)
    if log is None:
        raise HTTPException(404, detail={"code": "WORKOUT_NOT_FOUND", "message": "일지를 찾을 수 없습니다"})
    await _visible_member(db, log.member_id, scope)
    return log


@router.patch("/{workout_id}", response_model=WorkoutLogOut)
async def update_workout(
    workout_id: str,
    payload: WorkoutLogUpdate,
    current: Employee = Depends(get_current_user),
    scope: str | None = Depends(branch_scope),
    db: AsyncSession = Depends(get_db),
) -> WorkoutLog:
    log = await db.get(WorkoutLog, workout_id)
    if log is None:
        raise HTTPException(404, detail={"code": "WORKOUT_NOT_FOUND", "message": "일지를 찾을 수 없습니다"})
    member = await _visible_member(db, log.member_id, scope)
    _ensure_can_write(member, current)

    data = payload.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        data["title"] = data["title"].strip()
    for key, value in data.items():
        if value is None and key in ("title", "performed_on", "weights", "cardio", "media"):
            continue  # 비우라는 뜻이 아니다 — 안 보낸 것과 같게 둔다
        setattr(log, key, value)
    await db.commit()
    await db.refresh(log)
    return log


@router.delete("/{workout_id}", status_code=204)
async def delete_workout(
    workout_id: str,
    current: Employee = Depends(get_current_user),
    scope: str | None = Depends(branch_scope),
    db: AsyncSession = Depends(get_db),
) -> None:
    log = await db.get(WorkoutLog, workout_id)
    if log is None:
        raise HTTPException(404, detail={"code": "WORKOUT_NOT_FOUND", "message": "일지를 찾을 수 없습니다"})
    member = await _visible_member(db, log.member_id, scope)
    _ensure_can_write(member, current)
    await db.delete(log)
    await db.commit()
