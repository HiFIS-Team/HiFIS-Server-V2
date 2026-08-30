"""WorkoutLog DTO — CLAUDE.md §3.4.

**들어올 때와 나갈 때의 자료 주소가 다르다.** DB 에는 `/uploads/..` 를 그대로
담고, 내려줄 때만 서명 URL(`/files/..?exp&sig`)로 바꾼다(§H2). 담을 때 서명을
붙이면 만료된 주소가 표에 영원히 남는다.
"""

from datetime import date
from typing import Annotated

from pydantic import AfterValidator, Field

from app.core.file_signing import unsign_upload_url
from app.enums import WorkoutKind, WorkoutMediaKind
from app.schemas.base import CamelModel, SignedUrl

#: 받아 적을 자료 주소 — 앱이 돌려보낸 서명 URL 을 원래 '/uploads/..' 로 되돌린다
RawUrl = Annotated[str, AfterValidator(unsign_upload_url)]

#: 표 한 장에 담을 수 있는 줄 수 — 사람이 손으로 적는 값이라 이 위는 사고다
MAX_ROWS = 60
#: 자료 묶음 개수 · 묶음 하나에 담기는 파일 수
MAX_GROUPS = 30
MAX_ITEMS = 20


class WeightRow(CamelModel):
    """웨이트 표 한 줄 — 운동부위 / 운동명 / 무게·횟수 / 세트수."""

    part: str = Field(default="", max_length=30)
    name: str = Field(default="", max_length=60)
    #: "60kg x 12" 처럼 한 칸에 적는다 — 맨몸·밴드처럼 무게가 없는 운동이 많다
    load: str = Field(default="", max_length=40)
    sets: str = Field(default="", max_length=20)


class CardioRow(CamelModel):
    """유산소 표 한 줄 — 운동명 / 시간."""

    name: str = Field(default="", max_length=60)
    duration: str = Field(default="", max_length=40)


class MediaItemIn(CamelModel):
    """올린 파일 하나 — `POST /workouts/media` 가 준 `url` 을 그대로 싣는다.

    앱은 목록에서 받은 **서명된** 주소를 그대로 되돌려 보낸다. [RawUrl] 이
    서명을 떼어 내므로 DB 에는 언제나 `/uploads/..` 만 남는다.
    """

    url: RawUrl = Field(max_length=500)
    kind: WorkoutMediaKind


class MediaItemOut(CamelModel):
    url: SignedUrl
    kind: WorkoutMediaKind


class MediaGroupIn(CamelModel):
    """자료 묶음 — 한 번에 올린 것들과 그에 대한 피드백 한 덩어리."""

    items: list[MediaItemIn] = Field(default_factory=list, max_length=MAX_ITEMS)
    feedback: str = Field(default="", max_length=2000)


class MediaGroupOut(CamelModel):
    items: list[MediaItemOut] = Field(default_factory=list)
    feedback: str = ""


class WorkoutMediaOut(CamelModel):
    """올린 자료의 주소 — 이걸 [WorkoutLogCreate.media] 에 그대로 실어 보낸다.

    **서명해서 내려준다.** 앱이 저장 전에 바로 미리보기를 그려야 하는데
    `/uploads/..` 는 열리지 않는다. 되돌려 받을 때 [MediaItemIn] 이 서명을
    떼어 내므로 DB 에는 원본 주소만 남는다.
    """

    url: SignedUrl
    kind: WorkoutMediaKind


class WorkoutLogCreate(CamelModel):
    member_id: str
    kind: WorkoutKind
    #: PT 만 준다 — 개인 운동에 보내면 서버가 무시하고 비운다
    session_no: int | None = Field(default=None, ge=1)
    title: str = Field(max_length=100)
    performed_on: date
    weights: list[WeightRow] = Field(default_factory=list, max_length=MAX_ROWS)
    cardio: list[CardioRow] = Field(default_factory=list, max_length=MAX_ROWS)
    media: list[MediaGroupIn] = Field(default_factory=list, max_length=MAX_GROUPS)
    trainer_feedback: str | None = Field(default=None, max_length=2000)


class WorkoutLogUpdate(CamelModel):
    """고칠 것만 보낸다 — 안 보낸 칸은 그대로 둔다.

    **회차(`session_no`)와 종류(`kind`)는 못 고친다.** 3회차를 5회차로 바꾸면
    회차가 겹치거나 비고, 개인 운동을 PT 로 바꾸면 결제한 회차가 몰래 깎인다.
    """

    title: str | None = Field(default=None, max_length=100)
    performed_on: date | None = None
    weights: list[WeightRow] | None = Field(default=None, max_length=MAX_ROWS)
    cardio: list[CardioRow] | None = Field(default=None, max_length=MAX_ROWS)
    media: list[MediaGroupIn] | None = Field(default=None, max_length=MAX_GROUPS)
    trainer_feedback: str | None = Field(default=None, max_length=2000)


class WorkoutLogOut(CamelModel):
    id: str
    member_id: str
    kind: WorkoutKind
    session_no: int | None = None
    title: str
    performed_on: date
    #: 비어 있으면 회원이 공개 주소에서 직접 쓴 줄이다
    author_id: str | None = None
    weights: list[WeightRow] = Field(default_factory=list)
    cardio: list[CardioRow] = Field(default_factory=list)
    media: list[MediaGroupOut] = Field(default_factory=list)
    trainer_feedback: str | None = None
