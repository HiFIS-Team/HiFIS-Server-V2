"""사내톡 열람 DTO — 관리자 이상 (개인정보처리방침 §8).

사내톡 화면이 쓰는 `ChatRoomOut`·`MessageOut` 과 **일부러 따로 둔다.**
그쪽은 '내 기준' 값(안읽음 수·알림 끔·반응)을 얹어 주는데 열람에는 뜻이 없고,
반대로 여기는 **전송 취소된 메시지**를 그대로 보여줘야 해서 모양이 다르다.
"""

from datetime import datetime

from app.enums import MessageKind
from app.schemas.base import CamelModel


class ChatAuditRoomOut(CamelModel):
    id: str
    name: str | None = None
    is_group: bool
    owner_id: str

    # 나간 사람 포함 — 지금 없어도 그때 대화에는 있었다
    member_ids: list[str] = []
    left_member_ids: list[str] = []

    message_count: int = 0
    last_message_at: datetime | None = None
    created_at: datetime


class ChatAuditMessageOut(CamelModel):
    id: str
    room_id: str
    sender_id: str
    body: str
    kind: MessageKind
    attachments: list = []
    reply_to_id: str | None = None

    # 값이 있으면 **보낸 사람이 전송 취소한** 메시지다. 본문은 그대로 남아 있다
    deleted_at: datetime | None = None

    created_at: datetime
