"""사내톡 REST 라우터 — 방·메시지·읽음 (CLAUDE.md §6.11).

실시간 수신/발신·타이핑은 WS /ws/chat (app/ws/chat.py). 여기선 방 관리·히스토리·전송(영속).
메시지 반응은 공통 POST /reactions (targetType=MESSAGE).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.storage import save_upload
from app.db.session import get_db
from app.enums import MessageKind, ReactionTargetType
from app.models.board.reaction import Reaction
from app.models.chat.chat import ChatRoom, ChatRoomMember, Message
from app.models.staff.employee import Employee
from app.schemas.chat.chat import (
    AttachmentOut,
    ChatMemberAdd,
    ChatRoomCreate,
    ChatRoomOut,
    ChatRoomUpdate,
    MessageCreate,
    MessageOut,
)
from app.services.chat import (
    broadcast_event,
    is_member,
    member_ids,
    post_message,
    read_counts,
    reply_refs,
    system_message,
)
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
    if not messages:
        return []
    agg = await aggregate_for(db, ReactionTargetType.MESSAGE, [m.id for m in messages])
    refs = await reply_refs(db, messages)
    reads = await read_counts(db, messages[0].room_id, messages)
    out = []
    for m in messages:
        model = MessageOut.model_validate(m)
        model.reactions = agg[m.id]
        model.reply_to = refs.get(m.reply_to_id or "")
        model.read_count = reads.get(m.id, 0)
        out.append(model)
    return out


async def _drop_reactions(db: AsyncSession, message_ids: list[str]) -> None:
    """메시지에 달린 반응을 지운다(commit 은 호출부에서).

    Reaction.target_id 는 다형 참조라 FK 가 없다 — 메시지가 없어져도
    행이 그대로 남으므로 여기서 직접 정리한다.
    """
    if not message_ids:
        return
    await db.execute(
        delete(Reaction).where(
            Reaction.target_type == ReactionTargetType.MESSAGE,
            Reaction.target_id.in_(message_ids),
        )
    )


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
    left: bool = Query(False, description="true 면 내가 나간 방(최근 나간 항목)"),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatRoomOut]:
    """내 대화 목록. `left=true` 면 **나간 방**을 대신 준다.

    나간 방도 행이 남아 있어서(§`ChatRoomMember.left_at`) 언제 나갔는지와
    그때까지의 대화를 다시 찾아볼 수 있다.
    """
    membership = ChatRoomMember.left_at.isnot(None) if left else ChatRoomMember.left_at.is_(None)
    my_rooms = (
        await db.scalars(
            select(ChatRoom)
            .join(ChatRoomMember, ChatRoomMember.room_id == ChatRoom.id)
            .where(ChatRoomMember.employee_id == current.id, membership)
        )
    ).all()
    rooms = [await _room_out(db, room, current.id) for room in my_rooms]
    # 최근 메시지(없으면 방 생성) 순으로 정렬
    rooms.sort(
        key=lambda r: r.last_message.created_at if r.last_message else r.updated_at, reverse=True
    )
    return rooms


@router.patch("/rooms/{room_id}", response_model=ChatRoomOut)
async def update_room(
    room_id: str,
    payload: ChatRoomUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatRoomOut:
    """방 이름 바꾸기 — 멤버 누구나. 바뀐 사실은 안내 메시지로 대화에 남는다.

    DM 은 이름이 없다(상대 이름으로 보인다) — 400 으로 막는다.
    """
    room = await _require_member(db, room_id, current.id)
    if not room.is_group:
        raise HTTPException(400, detail={"code": "NOT_GROUP_ROOM", "message": "1:1 대화는 이름을 바꿀 수 없습니다"})
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, detail={"code": "NAME_REQUIRED", "message": "방 이름을 입력하세요"})
    if name != room.name:
        room.name = name
        await db.commit()
        await system_message(
            db, room_id=room_id, actor_id=current.id, body=f"{current.name}님이 방 이름을 '{name}'(으)로 바꿨어요"
        )
    await db.refresh(room)
    return await _room_out(db, room, current.id)


@router.post("/rooms/{room_id}/members", response_model=ChatRoomOut, status_code=201)
async def add_members(
    room_id: str,
    payload: ChatMemberAdd,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatRoomOut:
    """멤버 초대.

    **DM 에 초대하면 그룹방이 된다** — 둘이던 대화에 셋째가 들어오면
    더 이상 1:1 이 아니다. 이름이 없으면 앱이 멤버 이름을 이어 붙여 보여준다.
    """
    room = await _require_member(db, room_id, current.id)
    already = set(await member_ids(db, room_id))
    wanted = {mid for mid in payload.member_ids if mid} - already
    if not wanted:
        raise HTTPException(400, detail={"code": "NO_MEMBERS", "message": "초대할 사람을 1명 이상 지정하세요"})

    people = (
        await db.scalars(
            select(Employee).where(Employee.id.in_(wanted), Employee.deleted_at.is_(None))
        )
    ).all()
    if len(people) != len(wanted):
        raise HTTPException(400, detail={"code": "MEMBER_NOT_FOUND", "message": "존재하지 않는 멤버가 있습니다"})

    for person in people:
        db.add(ChatRoomMember(room_id=room_id, employee_id=person.id))
    if not room.is_group:
        room.is_group = True
    await db.commit()

    names = ", ".join(p.name for p in people)
    await system_message(
        db, room_id=room_id, actor_id=current.id, body=f"{current.name}님이 {names}님을 초대했어요"
    )
    await db.refresh(room)
    return await _room_out(db, room, current.id)


@router.delete("/rooms/{room_id}/members/me", status_code=204)
async def leave_room(
    room_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """방 나가기 — 내 멤버십만 지운다. 대화와 남의 기록은 그대로 둔다.

    마지막 사람이 나가면 방을 지운다. 아무도 못 여는 방이 남을 이유가 없다.
    """
    await _require_member(db, room_id, current.id)
    # 안내를 먼저 남긴다 — 나간 뒤에는 이 방에 글을 쓸 수 없다
    await system_message(db, room_id=room_id, actor_id=current.id, body=f"{current.name}님이 나갔어요")

    membership = await db.scalar(
        select(ChatRoomMember).where(
            ChatRoomMember.room_id == room_id, ChatRoomMember.employee_id == current.id
        )
    )
    if membership is not None:
        # 행을 지우지 않고 나간 시각만 찍는다 — '최근 나간 항목'에서 다시 찾는다
        membership.left_at = datetime.now(timezone.utc)
        await db.commit()

    # **마지막 사람이 나가도 방을 지우지 않는다.** 지우면 나간 사람의
    # '최근 나간 항목'에서 그 방이 통째로 사라져 다시 들여다볼 수 없다.
    # 아무도 없는 방은 활성 목록에 안 뜨므로 걸리적거리지도 않는다.
    return None


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
    # 전송 취소한 메시지는 빼고 준다(소프트 삭제) — 답글 인용은 reply_to 가 따로 알린다
    stmt = select(Message).where(Message.room_id == room_id, Message.deleted_at.is_(None))
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
        db,
        room_id=room_id,
        sender_id=current.id,
        body=payload.body,
        attachments=payload.attachments,
        reply_to_id=payload.reply_to_id,
    )
    return (await _messages_out(db, [message]))[0]


@router.post("/rooms/{room_id}/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    room_id: str,
    file: UploadFile = File(...),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttachmentOut:
    """사내톡에 붙일 파일 올리기 — 올린 주소를 메시지 `attachments` 에 넣어 보낸다.

    문서함(`POST /documents`)과 나눈 이유: 그쪽은 폴더·스코프가 필요한 **문서 관리**고,
    대화에 붙는 사진 한 장은 그 트리에 들어갈 것이 아니다.
    """
    await _require_member(db, room_id, current.id)
    url, ext, size = await save_upload(file)
    return AttachmentOut(
        url=url, name=file.filename or f"file.{ext}", ext=ext, size=size
    )


@router.delete("/rooms/{room_id}/messages/{message_id}", status_code=204)
async def delete_message(
    room_id: str,
    message_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """전송 취소 — **본인이 보낸 것만.** 행은 남기고 목록에서만 뺀다.

    지운 것을 남에게도 즉시 없애야 해서 `type=delete` 로 브로드캐스트한다.
    """
    await _require_member(db, room_id, current.id)
    message = await db.get(Message, message_id)
    if message is None or message.room_id != room_id or message.deleted_at is not None:
        raise HTTPException(404, detail={"code": "MESSAGE_NOT_FOUND", "message": "메시지를 찾을 수 없습니다"})
    if message.sender_id != current.id:
        raise HTTPException(403, detail={"code": "NOT_MESSAGE_SENDER", "message": "본인이 보낸 메시지만 취소할 수 있습니다"})
    message.deleted_at = datetime.now(timezone.utc)
    # 말풍선이 사라지면 거기 달린 반응도 갈 곳이 없다.
    # Reaction 은 target_id 가 FK 가 아니라서(다형 참조) 직접 지운다.
    await _drop_reactions(db, [message_id])
    await db.commit()
    await broadcast_event(db, room_id=room_id, type="delete", messageId=message_id)
    return None


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
    # 전송 취소한 메시지는 미리보기에도 안읽음 수에도 안 들어간다
    last_msg = await db.scalar(
        select(Message)
        .where(Message.room_id == room.id, Message.deleted_at.is_(None))
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    # 안읽음 = 내 last_read 이후 도착한 남의 메시지 수.
    # 시스템 안내(초대·나가기·이름 변경)는 세지 않는다 — 누가 나갔다고
    # 방에 빨간 배지가 붙으면 읽을 것이 있는 줄 알고 들어가게 된다.
    unread_stmt = select(func.count()).select_from(Message).where(
        Message.room_id == room.id,
        Message.deleted_at.is_(None),
        Message.sender_id != me,
        Message.kind == MessageKind.TEXT,
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
