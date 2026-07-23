"""사내톡 서비스 — 메시지 영속화 + 실시간 브로드캐스트 (CLAUDE.md §6.11, §9.3).

REST 전송·WS 전송 공통 진입점. 방 멤버에게 인메모리 매니저로 팬아웃.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collab.chat import ChatRoomMember, Message
from app.schemas.collab.chat import MessageOut
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

    payload = {
        "type": "message",
        "roomId": room_id,
        "message": MessageOut.model_validate(message).model_dump(by_alias=True, mode="json"),
    }
    await manager.send_to(await member_ids(db, room_id), payload)
    return message


async def broadcast_event(
    db: AsyncSession, *, room_id: str, exclude: str | None = None, **payload
) -> None:
    """타이핑·읽음 등 비영속 이벤트를 방 멤버에게 전송(발신자 제외 옵션)."""
    payload["roomId"] = room_id
    targets = [m for m in await member_ids(db, room_id) if m != exclude]
    await manager.send_to(targets, payload)
