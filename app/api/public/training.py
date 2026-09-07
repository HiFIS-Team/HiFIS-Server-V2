"""회원이 자기 수업을 보는 화면 — **로그인 없는** 공개 주소 (`/training/{token}`).

주소가 담는 값은 `members.training_token` 이다 (회원 id 가 아니다 — 문자로
나가는 주소라 새면 갈아 끼울 수 있어야 한다).

**로그인이 없다는 게 이 파일의 전부다.** 그래서 넷을 지킨다.

1. 내주는 것은 **이름·운동을 하는 이유·일지·영양제**뿐이다. 전화번호·결제액·
   남은 회차·내부 id 는 안 나간다 (`TrainingLogOut` 에 그 칸 자체가 없다)
2. **PT 일지는 읽기만.** 회차 기록은 트레이너가 쓰는 것이라, 여기서 고치면
   결제한 회차와 어긋난다
3. 개인 운동은 쓰고 고칠 수 있되 **자기가 쓴 것만**이다. 트레이너가 대신
   적어 준 개인 운동을 회원이 덮어쓰면 원본이 사라진다
4. 트레이너 피드백은 **받는 자리 자체가 없다** (`PersonalLogIn`)
5. **영양제도 읽기만.** 몸에 넣는 것을 권하는 자리라 회원이 고치면 트레이너가
   권한 것과 달라진다 — 쓰는 길(`POST`)을 아예 안 뚫었다

앱(트레이너)이 쓰는 길은 `app/api/members/workouts.py` 다. 여기는 회원 쪽
길이라 권한 규칙이 정반대라서 라우터를 나눠 뒀다 — 한 파일에 두면 `if` 로
갈리다가 언젠가 한쪽 규칙이 다른 쪽에 샌다.
"""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ratelimit import limiter
from app.core.storage import save_workout_media
from app.db.session import get_db
from app.enums import WorkoutKind
from app.models.members.member import Member
from app.models.members.supplement import Supplement
from app.models.members.workout import WorkoutLog
from app.models.staff.employee import Employee
from app.schemas.members.training import (
    PersonalLogIn,
    TrainingLogOut,
    TrainingPageOut,
    TrainingSupplementOut,
)
from app.schemas.members.workout import WorkoutMediaOut

router = APIRouter(tags=["training"])

#: 회원 한 사람이 남길 수 있는 개인 운동 장 수 — 폼을 돌려 쌓는 것을 막는다
MAX_PERSONAL_LOGS = 500


async def _member_of(token: str, db: AsyncSession) -> Member:
    member = await db.scalar(select(Member).where(Member.training_token == token))
    if member is None:
        raise HTTPException(
            404, detail={"code": "TRAINING_NOT_FOUND", "message": "주소가 올바르지 않습니다"}
        )
    return member


def _to_out(log: WorkoutLog) -> TrainingLogOut:
    return TrainingLogOut(
        id=log.id,
        kind=log.kind,
        session_no=log.session_no,
        title=log.title,
        performed_on=log.performed_on,
        weights=log.weights or [],
        cardio=log.cardio or [],
        media=log.media or [],
        trainer_feedback=log.trainer_feedback,
        # 작성자가 비어 있으면 회원이 이 화면에서 쓴 줄이다
        mine=log.kind is WorkoutKind.PERSONAL and log.author_id is None,
    )


async def _own_personal_log(token: str, log_id: str, db: AsyncSession) -> WorkoutLog:
    """회원이 고칠 수 있는 줄만 — 남의 일지도, 트레이너가 쓴 줄도 아니다."""
    member = await _member_of(token, db)
    log = await db.get(WorkoutLog, log_id)
    # 있고 없고를 구분해 알려 주지 않는다 — id 를 찍어 보며 남의 일지를 세는 길이 된다
    if (
        log is None
        or log.member_id != member.id
        or log.kind is not WorkoutKind.PERSONAL
        or log.author_id is not None
    ):
        raise HTTPException(
            404, detail={"code": "WORKOUT_NOT_FOUND", "message": "고칠 수 있는 일지가 아닙니다"}
        )
    return log


@router.get("/training/{token}", response_model=TrainingPageOut)
@limiter.limit("60/minute")
async def training_page(
    request: Request, token: str, db: AsyncSession = Depends(get_db)
) -> TrainingPageOut:
    member = await _member_of(token, db)
    trainer = await db.get(Employee, member.owner_trainer_id)

    result = await db.execute(
        select(WorkoutLog)
        .where(WorkoutLog.member_id == member.id)
        .order_by(WorkoutLog.performed_on.desc(), WorkoutLog.created_at.desc())
    )
    logs = list(result.scalars().all())

    # PT 는 회차 순으로 세운다 — 밀린 일지를 나중에 채우면 날짜 순이 뒤섞인다
    pt = sorted(
        (log for log in logs if log.kind is WorkoutKind.PT),
        key=lambda log: log.session_no or 0,
    )
    personal = [log for log in logs if log.kind is WorkoutKind.PERSONAL]

    # 영양제 — 트레이너가 세운 차례 그대로 (먹는 순서로 옮겨 둔다)
    pills = await db.execute(
        select(Supplement)
        .where(Supplement.member_id == member.id)
        .order_by(Supplement.sort_order, Supplement.created_at)
    )

    return TrainingPageOut(
        member_name=member.name,
        trainer_name=trainer.name if trainer else "",
        goals=list(member.goals or []),
        pt=[_to_out(log) for log in pt],
        personal=[_to_out(log) for log in personal],
        supplements=[
            TrainingSupplementOut.model_validate(row) for row in pills.scalars().all()
        ],
    )


@router.post("/training/{token}/media", response_model=WorkoutMediaOut, status_code=201)
@limiter.limit("30/minute")  # 로그인 없는 업로드다 — 크기·확장자는 storage 가 막는다
async def upload_training_media(
    request: Request,
    token: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> WorkoutMediaOut:
    await _member_of(token, db)
    url, kind = await save_workout_media(file)
    return WorkoutMediaOut(url=url, kind=kind)


@router.post("/training/{token}/personal", response_model=TrainingLogOut, status_code=201)
@limiter.limit("30/minute")
async def create_personal_log(
    request: Request,
    token: str,
    payload: PersonalLogIn,
    db: AsyncSession = Depends(get_db),
) -> TrainingLogOut:
    member = await _member_of(token, db)

    result = await db.execute(
        select(WorkoutLog.id).where(
            WorkoutLog.member_id == member.id, WorkoutLog.kind == WorkoutKind.PERSONAL
        )
    )
    if len(result.all()) >= MAX_PERSONAL_LOGS:
        raise HTTPException(
            400,
            detail={"code": "TOO_MANY_LOGS", "message": "개인 운동을 더 담을 수 없어요"},
        )

    log = WorkoutLog(
        member_id=member.id,
        kind=WorkoutKind.PERSONAL,
        session_no=None,
        title=payload.title.strip(),
        performed_on=payload.performed_on,
        author_id=None,  # 회원이 직접 쓴 줄
        weights=[row.model_dump() for row in payload.weights],
        cardio=[row.model_dump() for row in payload.cardio],
        media=[group.model_dump() for group in payload.media],
        trainer_feedback=None,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return _to_out(log)


@router.patch("/training/{token}/personal/{log_id}", response_model=TrainingLogOut)
@limiter.limit("30/minute")
async def update_personal_log(
    request: Request,
    token: str,
    log_id: str,
    payload: PersonalLogIn,
    db: AsyncSession = Depends(get_db),
) -> TrainingLogOut:
    log = await _own_personal_log(token, log_id, db)
    log.title = payload.title.strip()
    log.performed_on = payload.performed_on
    log.weights = [row.model_dump() for row in payload.weights]
    log.cardio = [row.model_dump() for row in payload.cardio]
    log.media = [group.model_dump() for group in payload.media]
    await db.commit()
    await db.refresh(log)
    return _to_out(log)


@router.delete("/training/{token}/personal/{log_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_personal_log(
    request: Request,
    token: str,
    log_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    log = await _own_personal_log(token, log_id, db)
    await db.delete(log)
    await db.commit()
