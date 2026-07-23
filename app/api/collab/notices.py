"""Notice 라우터 — CLAUDE.md §6.4. 작성=[ADMIN,MANAGER], 조회=인증."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import ReactionTargetType, Role
from app.models.org.employee import Employee
from app.models.collab.notice import Notice
from app.models.collab.reaction import Reaction
from app.schemas.collab.notice import NoticeCreate, NoticeOut, NoticeUpdate
from app.services.reactions import aggregate_for

router = APIRouter(prefix="/notices", tags=["notices"], dependencies=[Depends(get_current_user)])


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "NOTICE_NOT_FOUND", "message": "공지를 찾을 수 없습니다"})


async def _to_out(db: AsyncSession, notices: list[Notice]) -> list[NoticeOut]:
    agg = await aggregate_for(db, ReactionTargetType.NOTICE, [n.id for n in notices])
    out = []
    for n in notices:
        model = NoticeOut.model_validate(n)
        model.reactions = agg[n.id]
        out.append(model)
    return out


@router.get("", response_model=list[NoticeOut])
async def list_notices(db: AsyncSession = Depends(get_db)) -> list[NoticeOut]:
    result = await db.execute(
        select(Notice).order_by(Notice.pinned.desc(), Notice.created_at.desc())
    )
    return await _to_out(db, list(result.scalars().all()))


@router.post("", response_model=NoticeOut, status_code=201)
async def create_notice(
    payload: NoticeCreate,
    current: Employee = Depends(require_role(Role.ADMIN, Role.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> NoticeOut:
    notice = Notice(title=payload.title, body=payload.body, pinned=payload.pinned, author_id=current.id)
    db.add(notice)
    await db.commit()
    await db.refresh(notice)
    return (await _to_out(db, [notice]))[0]


@router.patch("/{notice_id}", response_model=NoticeOut, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def update_notice(
    notice_id: str, payload: NoticeUpdate, db: AsyncSession = Depends(get_db)
) -> NoticeOut:
    notice = await db.get(Notice, notice_id)
    if notice is None:
        raise _not_found()
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(notice, key, value)
    await db.commit()
    await db.refresh(notice)
    return (await _to_out(db, [notice]))[0]


@router.delete("/{notice_id}", status_code=204, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def delete_notice(notice_id: str, db: AsyncSession = Depends(get_db)) -> None:
    notice = await db.get(Notice, notice_id)
    if notice is None:
        raise _not_found()
    await db.execute(
        delete(Reaction).where(
            Reaction.target_type == ReactionTargetType.NOTICE,
            Reaction.target_id == notice_id,
        )
    )
    await db.delete(notice)
    await db.commit()
    return None
