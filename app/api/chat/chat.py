"""사내톡 REST 라우터 — 방·메시지·읽음 (CLAUDE.md §6.11).

실시간 수신/발신·타이핑은 WS /ws/chat (app/ws/chat.py). 여기선 방 관리·히스토리·전송(영속).
메시지 반응은 공통 POST /reactions (targetType=MESSAGE).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.enums import ReactionTargetType
from app.models.chat.chat import ChatRoom, ChatRoomMember, Message
from app.models.staff.employee import Employee
from app.schemas.chat.chat import ChatRoomCreate, ChatRoomOut, MessageCreate, MessageOut
from app.services.chat import broadcast_event, is_member, member_ids, post_message
from app.services.reactions import aggregate_for

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(get_current_user)])


async def _require_member(db: AsyncSession, room_id: str, employee_id: str) -> ChatRoom:
    room = await db.get(ChatRoom, room_id)
    if room is None:
        raise HTTPException(404, detail={"code": "ROOM_NOT_FOUND", "message": "채팅방을 찾을 수 없습니다"})
    if not await is_member(db, room_id, employee_id):
        raise HTTPException(403, detail={"code": "NOT_ROOM_MEMBER", "message": "이 방의 멤버가 아닙니다"})
    return room


async def _messages_out(db: AsyncSession, messages: list[Message]) -> list[MessageOut]:
    agg = await aggregate_for(db, ReactionTargetType.MESSAGE, [m.id for m in messages])
    out = []
    for m in messages:
        model = MessageOut.model_validate(m)
        model.reactions = agg[m.id]
        out.append(model)
    return out


async def _find_dm(db: AsyncSession, a: str, b: str) -> ChatRoom | None:
    """a·b 두 사람만의 기존 DM 방(있으면 재사용)."""
    shared = (
        await db.scalars(
            select(ChatRoomMember.room_id)
            .where(ChatRoomMember.employee_id.in_([a, b]))
            .group_by(ChatRoomMember.room_id)
            .having(func.count() == 2)
        )
    ).all()
    for room_id in shared:
        room = await db.get(ChatRoom, room_id)
        if room and not room.is_group:
            total = await db.scalar(
                select(func.count()).select_from(ChatRoomMember).where(ChatRoomMember.room_id == room_id)
            )
            if total == 2:
                return room
    return None


# ---------- 방 ----------
@router.post("/rooms", response_model=ChatRoomOut, status_code=201)
async def create_room(
    payload: ChatRoomCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatRoomOut:
    members = {current.id, *payload.member_ids}
    members.discard("")
    others = members - {current.id}
    if not others:
        raise HTTPException(400, detail={"code": "NO_MEMBERS", "message": "상대를 1명 이상 지정하세요"})
    # 멤버 실존 검사
    valid = await db.scalar(
        select(func.count()).select_from(Employee).where(Employee.id.in_(members), Employee.deleted_at.is_(None))
    )
    if valid != len(members):
        raise HTTPException(400, detail={"code": "MEMBER_NOT_FOUND", "message": "존재하지 않는 멤버가 있습니다"})

    # 1:1 DM 은 중복 생성 방지 → 기존 방 재사용
    if not payload.is_group and len(members) == 2:
        existing = await _find_dm(db, current.id, next(iter(others)))
        if existing is not None:
            return await _room_out(db, existing, current.id)

    room = ChatRoom(name=payload.name, is_group=payload.is_group, owner_id=current.id)
    db.add(room)
    await db.flush()
    for mid in members:
        db.add(ChatRoomMember(room_id=room.id, employee_id=mid))
    await db.commit()
    await db.refresh(room)
    return await _room_out(db, room, current.id)


@router.get("/rooms", response_model=list[ChatRoomOut])
async def list_rooms(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatRoomOut]:
    my_rooms = (
        await db.scalars(
            select(ChatRoom)
            .join(ChatRoomMember, ChatRoomMember.room_id == ChatRoom.id)
            .where(ChatRoomMember.employee_id == current.id)
        )
    ).all()
    rooms = [await _room_out(db, room, current.id) for room in my_rooms]
    # 최근 메시지(없으면 방 생성) 순으로 정렬
    rooms.sort(
        key=lambda r: r.last_message.created_at if r.last_message else r.updated_at, reverse=True
    )
    return rooms


# ---------- 메시지 ----------
@router.get("/rooms/{room_id}/messages", response_model=list[MessageOut])
async def list_messages(
    room_id: str,
    before: datetime | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    await _require_member(db, room_id, current.id)
    stmt = select(Message).where(Message.room_id == room_id)
    if before is not None:
        stmt = stmt.where(Message.created_at < before)
    stmt = stmt.order_by(Message.created_at.desc()).limit(limit)
    newest_first = list((await db.scalars(stmt)).all())
    newest_first.reverse()  # 오래된→최신 순으로 반환(렌더 편의)
    return await _messages_out(db, newest_first)


@router.post("/rooms/{room_id}/messages", response_model=MessageOut, status_code=201)
async def send_message(
    room_id: str,
    payload: MessageCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    await _require_member(db, room_id, current.id)
    message = await post_message(
        db, room_id=room_id, sender_id=current.id, body=payload.body, attachments=payload.attachments
    )
    return (await _messages_out(db, [message]))[0]


@router.post("/rooms/{room_id}/read", status_code=204)
async def mark_read(
    room_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_member(db, room_id, current.id)
    now = datetime.now(timezone.utc)
    membership = await db.scalar(
        select(ChatRoomMember).where(
            ChatRoomMember.room_id == room_id, ChatRoomMember.employee_id == current.id
        )
    )
    membership.last_read_at = now
    await db.commit()
    await broadcast_event(
        db, room_id=room_id, exclude=current.id, type="read",
        employeeId=current.id, lastReadAt=now.isoformat(),
    )
    return None


# ---------- 헬퍼 ----------
async def _room_out(db: AsyncSession, room: ChatRoom, me: str) -> ChatRoomOut:
    last_read = await db.scalar(
        select(ChatRoomMember.last_read_at).where(
            ChatRoomMember.room_id == room.id, ChatRoomMember.employee_id == me
        )
    )
    members = await member_ids(db, room.id)
    last_msg = await db.scalar(
        select(Message).where(Message.room_id == room.id).order_by(Message.created_at.desc()).limit(1)
    )
    # 안읽음 = 내 last_read 이후 도착한 남의 메시지 수
    unread_stmt = select(func.count()).select_from(Message).where(
        Message.room_id == room.id, Message.sender_id != me
    )
    if last_read is not None:
        unread_stmt = unread_stmt.where(Message.created_at > last_read)
    unread = await db.scalar(unread_stmt)
    return ChatRoomOut(
        id=room.id,
        name=room.name,
        is_group=room.is_group,
        owner_id=room.owner_id,
        member_ids=members,
        last_message=(await _messages_out(db, [last_msg]))[0] if last_msg else None,
        unread_count=unread or 0,
        updated_at=room.updated_at,
    )
