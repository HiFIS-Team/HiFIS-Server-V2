"""사내톡 서비스 — 메시지 영속화 + 실시간 브로드캐스트 (CLAUDE.md §6.11, §9.3).

REST 전송·WS 전송 공통 진입점. 방 멤버에게 인메모리 매니저로 팬아웃.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collab.chat import ChatRoom, ChatRoomMember, Message
from app.models.org.employee import Employee
from app.schemas.collab.chat import MessageOut
from app.services import notification_texts as ntext
from app.services.notifications import send_push
from app.ws.manager import manager


async def member_ids(db: AsyncSession, room_id: str) -> list[str]:
    rows = await db.scalars(
        select(ChatRoomMember.employee_id).where(ChatRoomMember.room_id == room_id)
    )
    return list(rows)


async def is_member(db: AsyncSession, room_id: str, employee_id: str) -> bool:
    found = await db.scalar(
        select(ChatRoomMember.id).where(
            ChatRoomMember.room_id == room_id, ChatRoomMember.employee_id == employee_id
        )
    )
    return found is not None


async def post_message(
    db: AsyncSession, *, room_id: str, sender_id: str, body: str, attachments: list[str]
) -> Message:
    """메시지 저장(commit) 후 방 멤버 전원에게 실시간 브로드캐스트."""
    message = Message(room_id=room_id, sender_id=sender_id, body=body, attachments=attachments)
    db.add(message)
    await db.commit()
    await db.refresh(message)

    members = await member_ids(db, room_id)
    payload = {
        "type": "message",
        "roomId": room_id,
        "message": MessageOut.model_validate(message).model_dump(by_alias=True, mode="json"),
    }
    await manager.send_to(members, payload)

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
    pushed = False
    for mid in members:
        if mid == sender_id:
            continue
        await send_push(db, employee_id=mid, **push)
        pushed = True
    if pushed:
        await db.commit()  # 만료 구독 정리분 반영(_push 예약 삭제)
    return message


async def broadcast_event(
    db: AsyncSession, *, room_id: str, exclude: str | None = None, **payload
) -> None:
    """타이핑·읽음 등 비영속 이벤트를 방 멤버에게 전송(발신자 제외 옵션)."""
    payload["roomId"] = room_id
    targets = [m for m in await member_ids(db, room_id) if m != exclude]
    await manager.send_to(targets, payload)
