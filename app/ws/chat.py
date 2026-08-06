"""사내톡 WebSocket — 실시간 수신/발신·타이핑·읽음 (CLAUDE.md §6.11, §9.3).

연결: ws://…/ws/chat?token=<accessToken> (브라우저 WS 는 헤더 못 넣어 쿼리로 JWT).
클라 → 서버 프레임:
  { "type": "message", "roomId", "body", "attachments"?, "replyToId"? }
  { "type": "typing",  "roomId", "isTyping" }
  { "type": "read",    "roomId" }
서버 → 클라: post_message/broadcast_event 가 보내는 {type, roomId, ...}.
  { "type": "message", "roomId", "message": MessageOut }
  { "type": "typing",  "roomId", "employeeId", "isTyping" }
  { "type": "read",    "roomId", "employeeId", "lastReadAt" }
  { "type": "delete",  "roomId", "messageId" }   — 전송 취소
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.chat.chat import ChatRoomMember
from app.models.staff.employee import Employee
from app.services.chat import broadcast_event, is_member, post_message
from app.ws.manager import manager

router = APIRouter()


async def _authenticate(token: str) -> str | None:
    """토큰 검증 → 유효하면 employee_id, 아니면 None."""
    try:
        payload = decode_token(token, expected_type="access")
    except Exception:
        return None
    async with SessionLocal() as db:
        employee = await db.get(Employee, payload.get("sub"))
        if employee is None or employee.deleted_at is not None:
            return None
        return employee.id


@router.websocket("/ws/chat")
async def ws_chat(ws: WebSocket, token: str = Query(...)) -> None:
    employee_id = await _authenticate(token)
    if employee_id is None:
        await ws.close(code=4401)  # 인증 실패(앱 정의 코드)
        return
    await manager.connect(employee_id, ws)
    try:
        while True:
            await _handle(employee_id, await ws.receive_json())
    except WebSocketDisconnect:
        manager.disconnect(employee_id, ws)
    except Exception:  # 프레임 파싱 오류 등 — 연결만 정리
        manager.disconnect(employee_id, ws)


async def _handle(employee_id: str, data: dict) -> None:
    room_id = data.get("roomId")
    typ = data.get("type")
    if not room_id:
        return
    async with SessionLocal() as db:
        if not await is_member(db, room_id, employee_id):
            return  # 방 멤버 아니면 무시

        if typ == "message":
            body = (data.get("body") or "").strip()
            if body:
                await post_message(
                    db, room_id=room_id, sender_id=employee_id,
                    body=body, attachments=data.get("attachments") or [],
                    reply_to_id=data.get("replyToId"),
                )
        elif typ == "typing":
            await broadcast_event(
                db, room_id=room_id, exclude=employee_id,
                type="typing", employeeId=employee_id, isTyping=bool(data.get("isTyping", True)),
            )
        elif typ == "read":
            now = datetime.now(timezone.utc)
            membership = await db.scalar(
                select(ChatRoomMember).where(
                    ChatRoomMember.room_id == room_id, ChatRoomMember.employee_id == employee_id
                )
            )
            if membership is not None:
                membership.last_read_at = now
                await db.commit()
            await broadcast_event(
                db, room_id=room_id, exclude=employee_id,
                type="read", employeeId=employee_id, lastReadAt=now.isoformat(),
            )
