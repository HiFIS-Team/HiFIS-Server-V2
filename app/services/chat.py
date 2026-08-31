"""사내톡 서비스 — 메시지 영속화 + 실시간 브로드캐스트 (CLAUDE.md §6.11, §9.3).

REST 전송·WS 전송 공통 진입점. 방 멤버에게 인메모리 매니저로 팬아웃.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.file_signing import unsign_upload_url
from app.enums import MessageKind
from app.models.chat.chat import ChatRoom, ChatRoomMember, Message
from app.models.staff.employee import Employee
from app.schemas.chat.chat import MessageOut, MessageRef
from app.services import notification_texts as ntext
from app.services.notifications import send_push
from app.ws.manager import manager


async def muted_ids(db: AsyncSession, room_id: str) -> set[str]:
    """이 방 알림을 꺼 둔 사람 — 푸시에서만 뺀다(대화·안읽음은 그대로)."""
    rows = await db.scalars(
        select(ChatRoomMember.employee_id).where(
            ChatRoomMember.room_id == room_id,
            ChatRoomMember.left_at.is_(None),
            ChatRoomMember.muted.is_(True),
        )
    )
    return set(rows)


async def member_ids(db: AsyncSession, room_id: str) -> list[str]:
    """지금 방에 있는 사람만 — 나간 사람(left_at)은 뺀다."""
    rows = await db.scalars(
        select(ChatRoomMember.employee_id).where(
            ChatRoomMember.room_id == room_id, ChatRoomMember.left_at.is_(None)
        )
    )
    return list(rows)


async def is_member(db: AsyncSession, room_id: str, employee_id: str) -> bool:
    found = await db.scalar(
        select(ChatRoomMember.id).where(
            ChatRoomMember.room_id == room_id,
            ChatRoomMember.employee_id == employee_id,
            ChatRoomMember.left_at.is_(None),
        )
    )
    return found is not None


async def read_counts(db: AsyncSession, room_id: str, messages: list[Message]) -> dict[str, int]:
    """메시지별 '나 말고 읽은 사람 수'.

    멤버들의 last_read_at 을 한 번만 읽어 파이썬에서 센다 — 메시지 30개 ×
    멤버 몇 명이라 쿼리를 메시지마다 날릴 이유가 없다.
    """
    rows = (
        await db.execute(
            select(ChatRoomMember.employee_id, ChatRoomMember.last_read_at).where(
                ChatRoomMember.room_id == room_id, ChatRoomMember.left_at.is_(None)
            )
        )
    ).all()
    out: dict[str, int] = {}
    for message in messages:
        out[message.id] = sum(
            1
            for employee_id, last_read in rows
            # 보낸 사람 본인은 세지 않는다 — '내가 읽음'은 뜻이 없다
            if employee_id != message.sender_id
            and last_read is not None
            and last_read >= message.created_at
        )
    return out


async def reply_refs(db: AsyncSession, messages: list[Message]) -> dict[str, MessageRef]:
    """답글이 가리키는 원문을 한 번에 읽어 온다.

    원문이 지워졌으면 본문 없이 `deleted=True` 로 준다 — 지운 내용이
    답글 인용으로 되살아나면 안 된다.
    """
    ids = {m.reply_to_id for m in messages if m.reply_to_id}
    if not ids:
        return {}
    originals = (await db.scalars(select(Message).where(Message.id.in_(ids)))).all()
    return {
        o.id: MessageRef(
            id=o.id,
            sender_id=o.sender_id,
            body="" if o.deleted_at is not None else o.body,
            deleted=o.deleted_at is not None,
        )
        for o in originals
    }


async def post_message(
    db: AsyncSession,
    *,
    room_id: str,
    sender_id: str,
    body: str,
    attachments: list[str],
    reply_to_id: str | None = None,
    kind: MessageKind = MessageKind.TEXT,
) -> Message:
    """메시지 저장(commit) 후 방 멤버 전원에게 실시간 브로드캐스트."""
    # 답글 대상이 이 방의 것이 아니면 그냥 무시한다 — 남의 방 메시지를 끌어오지 못하게
    if reply_to_id is not None:
        original = await db.get(Message, reply_to_id)
        if original is None or original.room_id != room_id:
            reply_to_id = None

    message = Message(
        room_id=room_id,
        sender_id=sender_id,
        body=body,
        # 앱은 올릴 때 받은 **서명된** 주소를 그대로 돌려보낸다. 그걸 그냥 담으면
        # 만료 시각이 DB 에 박혀서 7일 뒤에 못 여는 주소가 된다 (§H2).
        # REST 와 WS 가 둘 다 여기를 지나므로 여기서 한 번만 벗긴다.
        attachments=[unsign_upload_url(url) or url for url in attachments],
        reply_to_id=reply_to_id,
        kind=kind,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    members = await member_ids(db, room_id)
    out = MessageOut.model_validate(message)
    out.reply_to = (await reply_refs(db, [message])).get(reply_to_id or "")
    payload = {
        "type": "message",
        "roomId": room_id,
        "message": out.model_dump(by_alias=True, mode="json"),
    }
    await manager.send_to(members, payload)

    # 시스템 안내는 푸시를 보내지 않는다 — 방을 나갔다고 알림이 갈 이유가 없다
    if kind is not MessageKind.TEXT:
        return message

    # 메시지마다 웹푸시(인스타처럼) — 보낸 사람 제외 방 멤버. 알림함엔 안 남김.
    room = await db.get(ChatRoom, room_id)
    sender = await db.get(Employee, sender_id)
    push = ntext.chat_message(
        room_id=room_id,
        sender_name=sender.name if sender else "새 메시지",
        is_group=bool(room and room.is_group),
        room_name=room.name if room else None,
        body=body,
    )
    silent = await muted_ids(db, room_id)
    pushed = False
    for mid in members:
        if mid == sender_id or mid in silent:
            continue
        await send_push(db, employee_id=mid, **push)
        pushed = True
    if pushed:
        await db.commit()  # 만료 구독 정리분 반영(_push 예약 삭제)
    return message


async def system_message(db: AsyncSession, *, room_id: str, actor_id: str, body: str) -> Message:
    """초대·나가기·이름 변경 안내를 대화에 남긴다.

    앱이 말풍선이 아니라 가운데 회색 한 줄로 그린다. 브로드캐스트를
    [post_message] 가 이미 하므로 다른 기기도 바로 받는다.
    """
    return await post_message(
        db,
        room_id=room_id,
        sender_id=actor_id,
        body=body,
        attachments=[],
        kind=MessageKind.SYSTEM,
    )


async def broadcast_event(
    db: AsyncSession, *, room_id: str, exclude: str | None = None, **payload
) -> None:
    """타이핑·읽음 등 비영속 이벤트를 방 멤버에게 전송(발신자 제외 옵션)."""
    payload["roomId"] = room_id
    targets = [m for m in await member_ids(db, room_id) if m != exclude]
    await manager.send_to(targets, payload)
