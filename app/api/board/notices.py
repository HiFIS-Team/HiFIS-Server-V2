"""Notice 라우터 — CLAUDE.md §6.4. 작성=전 직원, 수정·삭제=작성자 본인+ADMIN·MANAGER, 조회=인증."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.enums import EmployeeStatus, ReactionTargetType, Role
from app.models.staff.employee import Employee
from app.models.board.notice import Notice
from app.models.board.notice_read import NoticeRead
from app.models.board.reaction import Reaction
from app.schemas.board.notice import (
    NoticeCreate,
    NoticeOut,
    NoticeReaderItem,
    NoticeReadersOut,
    NoticeUpdate,
)
from app.services import notification_texts as ntext
from app.services.notifications import notify
from app.services.reactions import aggregate_for

router = APIRouter(prefix="/notices", tags=["notices"], dependencies=[Depends(get_current_user)])


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "NOTICE_NOT_FOUND", "message": "공지를 찾을 수 없습니다"})


def _can_edit(notice: Notice, current: Employee) -> bool:
    # 작성자 본인 또는 ADMIN·MANAGER(+MASTER) → 수정·삭제 허용
    return notice.author_id == current.id or current.role in (Role.MASTER, Role.ADMIN, Role.MANAGER)


async def _to_out(db: AsyncSession, notices: list[Notice], current: Employee) -> list[NoticeOut]:
    ids = [n.id for n in notices]
    agg = await aggregate_for(db, ReactionTargetType.NOTICE, ids)
    counts: dict[str, int] = {}
    mine: set[str] = set()
    if ids:  # 읽음 집계 — 목록 N+1 없이 한 번에
        for nid, cnt in (
            await db.execute(
                select(NoticeRead.notice_id, func.count())
                .where(NoticeRead.notice_id.in_(ids))
                .group_by(NoticeRead.notice_id)
            )
        ).all():
            counts[nid] = cnt
        mine = set(
            (
                await db.scalars(
                    select(NoticeRead.notice_id).where(
                        NoticeRead.notice_id.in_(ids), NoticeRead.employee_id == current.id
                    )
                )
            ).all()
        )
    out = []
    for n in notices:
        model = NoticeOut.model_validate(n)
        model.reactions = agg[n.id]
        model.read_count = counts.get(n.id, 0)
        model.read_by_me = n.id in mine
        out.append(model)
    return out


@router.get("", response_model=list[NoticeOut])
async def list_notices(
    current: Employee = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[NoticeOut]:
    result = await db.execute(
        select(Notice).order_by(Notice.pinned.desc(), Notice.created_at.desc())
    )
    return await _to_out(db, list(result.scalars().all()), current)


@router.post("", response_model=NoticeOut, status_code=201)
async def create_notice(
    payload: NoticeCreate,
    current: Employee = Depends(get_current_user),  # 작성=전 직원(공지로 서로 요청·알림)
    db: AsyncSession = Depends(get_db),
) -> NoticeOut:
    notice = Notice(title=payload.title, body=payload.body, pinned=payload.pinned, author_id=current.id)
    db.add(notice)
    await db.flush()  # notice.id 확보(알림 링크용)
    # 새 공지 알림(+웹푸시) — 재직 중 전원(어드민 포함, 작성자만 제외)
    recipients = (
        await db.scalars(
            select(Employee.id).where(
                Employee.status == EmployeeStatus.ACTIVE,
                Employee.deleted_at.is_(None),
                Employee.id != current.id,
            )
        )
    ).all()
    text = ntext.new_notice(notice.title, notice.body, notice.id)
    for eid in recipients:
        await notify(db, employee_id=eid, **text)
    await db.commit()
    await db.refresh(notice)
    return (await _to_out(db, [notice], current))[0]


@router.post("/{notice_id}/read", status_code=204)
async def mark_notice_read(
    notice_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """공지 열람 시 읽음 처리 — (공지·본인)당 1회, 멱등."""
    notice = await db.get(Notice, notice_id)
    if notice is None:
        raise _not_found()
    exists = await db.scalar(
        select(NoticeRead).where(
            NoticeRead.notice_id == notice_id, NoticeRead.employee_id == current.id
        )
    )
    if exists is None:
        db.add(NoticeRead(notice_id=notice_id, employee_id=current.id))
        await db.commit()
    return None


@router.get("/{notice_id}/readers", response_model=NoticeReadersOut)
async def notice_readers(
    notice_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoticeReadersOut:
    """확인 현황 — 대상 전원(작성자 제외 재직자) + 사람별 읽음 여부."""
    notice = await db.get(Notice, notice_id)
    if notice is None:
        raise _not_found()
    recipients = (
        await db.execute(
            select(Employee)
            .where(
                Employee.status == EmployeeStatus.ACTIVE,
                Employee.deleted_at.is_(None),
                Employee.id != notice.author_id,
            )
            .order_by(Employee.name)
        )
    ).scalars().all()
    reads = {
        r.employee_id: r.read_at
        for r in (
            await db.execute(select(NoticeRead).where(NoticeRead.notice_id == notice_id))
        ).scalars().all()
    }
    people = [
        NoticeReaderItem(
            employee_id=e.id,
            name=e.name,
            avatar_color=e.avatar_color,
            avatar_url=e.avatar_url,
            read_at=reads.get(e.id),
        )
        for e in recipients
    ]
    read_count = sum(1 for e in recipients if e.id in reads)
    return NoticeReadersOut(total=len(recipients), read_count=read_count, people=people)


@router.patch("/{notice_id}", response_model=NoticeOut)
async def update_notice(
    notice_id: str,
    payload: NoticeUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoticeOut:
    notice = await db.get(Notice, notice_id)
    if notice is None:
        raise _not_found()
    if not _can_edit(notice, current):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 공지 또는 관리자만 수정할 수 있습니다"})
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(notice, key, value)
    await db.commit()
    await db.refresh(notice)
    return (await _to_out(db, [notice], current))[0]


@router.delete("/{notice_id}", status_code=204)
async def delete_notice(
    notice_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    notice = await db.get(Notice, notice_id)
    if notice is None:
        raise _not_found()
    if not _can_edit(notice, current):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 공지 또는 관리자만 삭제할 수 있습니다"})
    await db.execute(
        delete(Reaction).where(
            Reaction.target_type == ReactionTargetType.NOTICE,
            Reaction.target_id == notice_id,
        )
    )
    await db.execute(delete(NoticeRead).where(NoticeRead.notice_id == notice_id))  # 읽음 기록도 정리
    await db.delete(notice)
    await db.commit()
    return None
