"""생일 축하 모달 — 오늘 생일인 사람과 축하 이모지 보내기 (2026-09-27 대표 요청).

생일 당일 앱을 열면 **생일자 말고 전원에게** 모달이 뜬다. 이모지를 누르면
생일자에게 `00님이 축하 이모지를 보냈어요!` 푸시가 간다.
권한을 안 가린다 — 로그인한 사람이면 누구나.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.periods import KST
from app.db.session import get_db
from app.models.staff.birthday_cheer import BirthdayCheer
from app.models.staff.employee import Employee
from app.schemas.base import CamelModel
from app.services import notification_texts as ntext
from app.services.birthdays import born_on
from app.services.notifications import notify

router = APIRouter(prefix="/birthdays", tags=["birthdays"])

#: 모달의 축하 이모지 — 하나뿐이라 앱이 고르지 않는다
CHEER_EMOJI = "🎉"


class BirthdayTodayOut(CamelModel):
    id: str
    name: str
    avatar_color: str
    #: 내가 이미 축하를 보냈나 — 보냈으면 모달이 이모지를 잠근다
    cheered: bool


def _today():
    return datetime.now(timezone.utc).astimezone(KST).date()


@router.get("/today", response_model=list[BirthdayTodayOut])
async def birthdays_today(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BirthdayTodayOut]:
    """오늘 생일인 사람 — **나는 뺀다** (내 생일에 나를 축하하는 모달은 없다)."""
    today = _today()
    people = [p for p in await born_on(db, today) if p.id != current.id]
    sent = set(
        await db.scalars(
            select(BirthdayCheer.to_id).where(
                BirthdayCheer.from_id == current.id, BirthdayCheer.day == today
            )
        )
    )
    return [
        BirthdayTodayOut(id=p.id, name=p.name, avatar_color=p.avatar_color, cheered=p.id in sent)
        for p in people
    ]


@router.post("/{employee_id}/cheer", status_code=204)
async def cheer(
    employee_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """축하 이모지 보내기 — **한 생일에 한 번**. 두 번째부터는 조용히 204."""
    today = _today()
    if employee_id == current.id or employee_id not in {p.id for p in await born_on(db, today)}:
        raise HTTPException(
            400, detail={"code": "NOT_BIRTHDAY", "message": "오늘 생일인 사람이 아니에요"}
        )
    db.add(BirthdayCheer(from_id=current.id, to_id=employee_id, day=today))
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return
    await notify(db, employee_id=employee_id, **ntext.birthday_cheer(current.name, CHEER_EMOJI))
    await db.commit()
