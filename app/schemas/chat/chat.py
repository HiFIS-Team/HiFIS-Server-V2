"""사내톡 DTO — CLAUDE.md §6.11."""

from datetime import datetime

from pydantic import Field

from app.enums import MessageKind
from app.schemas.base import CamelModel, SignedUrl
from app.schemas.board.reaction import ReactionAgg


class ChatRoomCreate(CamelModel):
    member_ids: list[str] = Field(default_factory=list)  # 나 제외 상대(서버가 나 포함)
    name: str | None = None
    is_group: bool = False


class ChatRoomUpdate(CamelModel):
    """방 이름 바꾸기 — 그룹방만."""

    name: str | None = None


class ChatMemberAdd(CamelModel):
    member_ids: list[str] = Field(default_factory=list)


class AttachmentOut(CamelModel):
    """올린 파일 한 개 — 이 `url` 을 MessageCreate.attachments 에 넣어 보낸다.

    응답 직렬화에서 `/uploads/...` 가 서명 붙은 `/files/...?exp&sig` 로 바뀐다.
    """

    url: SignedUrl
    name: str
    ext: str
    size: int


class MessageCreate(CamelModel):
    body: str
    attachments: list[str] = Field(default_factory=list)
    reply_to_id: str | None = None


class MessageRef(CamelModel):
    """답글이 가리키는 원문 — 말풍선 위에 한 줄로 인용된다.

    원문이 지워졌으면 deleted=true 이고 body 는 비어 온다.
    앱이 '삭제된 메시지'로 그리라는 뜻이다.
    """

    id: str
    sender_id: str
    body: str = ""
    deleted: bool = False


class MessageOut(CamelModel):
    id: str
    room_id: str
    sender_id: str
    body: str
    kind: MessageKind = MessageKind.TEXT
    attachments: list[str] = Field(default_factory=list)
    reactions: list[ReactionAgg] = Field(default_factory=list)
    reply_to: MessageRef | None = None

    # 나 말고 이 메시지를 읽은 사람 수 — 내 말풍선의 '읽음' 표시에 쓴다.
    # DM 은 1 이면 읽은 것이고, 그룹은 숫자를 그대로 보여주면 된다.
    read_count: int = 0

    created_at: datetime


class ChatRoomOut(CamelModel):
    id: str
    name: str | None = None
    is_group: bool
    owner_id: str
    member_ids: list[str] = Field(default_factory=list)
    last_message: MessageOut | None = None
    unread_count: int = 0
    updated_at: datetime
