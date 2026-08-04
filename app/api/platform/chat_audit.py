"""사내톡 열람 — 관리자 이상 (개인정보처리방침 §8).

**읽기 전용이고 사내톡 라우터를 안 건드린다.** `/chat/*` 은 멤버만 통과하는
가드가 촘촘히 걸려 있어서 거기에 예외를 뚫으면 일반 직원에게 새기 쉽다.
게이트를 한 파일에 모아 두면 '누가 볼 수 있나'를 한 곳에서 확인할 수 있다.

읽음 처리를 하지 않는다 — 열람은 `last_read_at` 을 건드릴 이유가 없고,
건드리면 그 방 사람들의 안읽음 수가 엉킨다.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.enums import Role
from app.models.chat.chat import ChatRoom, ChatRoomMember, Message
from app.schemas.platform.chat_audit import ChatAuditMessageOut, ChatAuditRoomOut

router = APIRouter(
    prefix="/audit/chat",
    tags=["audit-chat"],
    dependencies=[Depends(require_role(Role.ADMIN))],  # MASTER 자동 승계
)


@router.get("/rooms", response_model=list[ChatAuditRoomOut])
async def list_rooms(db: AsyncSession = Depends(get_db)) -> list[ChatAuditRoomOut]:
    """전사 대화방 — 최근 대화가 있는 방부터"""
    rooms = list((await db.scalars(select(ChatRoom))).all())
    if not rooms:
        return []
    room_ids = [room.id for room in rooms]

    members: dict[str, list[str]] = {room_id: [] for room_id in room_ids}
    left: dict[str, list[str]] = {room_id: [] for room_id in room_ids}
    for row in (
        await db.execute(
            select(ChatRoomMember.room_id, ChatRoomMember.employee_id, ChatRoomMember.left_at).where(
                ChatRoomMember.room_id.in_(room_ids)
            )
        )
    ).all():
        (left if row.left_at is not None else members)[row.room_id].append(row.employee_id)

    # 전송 취소분도 센다 — 취소한 사실 자체가 봐야 할 값이다
    stats = {
        row.room_id: (row.count, row.last_at)
        for row in (
            await db.execute(
                select(
                    Message.room_id,
                    func.count(Message.id).label("count"),
                    func.max(Message.created_at).label("last_at"),
                )
                .where(Message.room_id.in_(room_ids))
                .group_by(Message.room_id)
            )
        ).all()
    }

    out = [
        ChatAuditRoomOut(
            id=room.id,
            name=room.name,
            is_group=room.is_group,
            owner_id=room.owner_id,
            member_ids=members[room.id],
            left_member_ids=left[room.id],
            message_count=stats.get(room.id, (0, None))[0],
            last_message_at=stats.get(room.id, (0, None))[1],
            created_at=room.created_at,
        )
        for room in rooms
    ]
    out.sort(key=lambda r: r.last_message_at or r.created_at, reverse=True)
    return out


@router.get("/rooms/{room_id}/messages", response_model=list[ChatAuditMessageOut])
async def list_messages(
    room_id: str,
    before: datetime | None = Query(None, description="이 시각 이전 (위로 더 보기)"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[Message]:
    """그 방의 대화 — **전송 취소된 것도 그대로 준다** (`deletedAt` 이 찍혀 온다)"""
    if await db.get(ChatRoom, room_id) is None:
        raise HTTPException(404, detail={"code": "ROOM_NOT_FOUND", "message": "채팅방을 찾을 수 없습니다"})
    stmt = select(Message).where(Message.room_id == room_id)
    if before is not None:
        stmt = stmt.where(Message.created_at < before)
    stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
    newest_first = list((await db.scalars(stmt)).all())
    newest_first.reverse()  # 오래된→최신 (화면 순서)
    return newest_first


@router.get("/messages", response_model=list[ChatAuditMessageOut])
async def search_messages(
    q: str | None = Query(None, min_length=1, description="본문에 든 말"),
    employee_id: str | None = Query(None, alias="employeeId", description="보낸 사람"),
    room_id: str | None = Query(None, alias="roomId"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[Message]:
    """전사 메시지 검색 — 방을 몰라도 말로 찾는다. 최신순"""
    stmt = select(Message).order_by(Message.created_at.desc()).limit(limit)
    if q:
        stmt = stmt.where(Message.body.ilike(f"%{q}%"))
    if employee_id:
        stmt = stmt.where(Message.sender_id == employee_id)
    if room_id:
        stmt = stmt.where(Message.room_id == room_id)
    return list((await db.scalars(stmt)).all())
