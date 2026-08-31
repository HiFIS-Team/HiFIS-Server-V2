"""환경정비 DTO — CLAUDE.md §4.2."""

from datetime import datetime

from pydantic import Field, computed_field

from app.schemas.base import CamelModel, SignedUrlOptional


class EnvItemCreate(CamelModel):
    branch_id: str
    name: str
    points: int = Field(gt=0)
    editable: bool = True
    sort_order: int = 1000  # 신규 커스텀 항목은 기본 목록(0~) 아래로


class EnvItemUpdate(CamelModel):
    name: str | None = None
    points: int | None = Field(default=None, gt=0)
    editable: bool | None = None
    sort_order: int | None = None  # 재정렬


class EnvItemOut(CamelModel):
    id: str
    branch_id: str
    name: str
    points: int
    editable: bool
    sort_order: int


class EnvLogCreate(CamelModel):
    env_item_id: str
    note: str | None = Field(default=None, max_length=80)  # 기타 등 write-in 텍스트 → 라벨 "기타(내용)"
    # 현수막처럼 확인이 필요한 항목만 채워 보낸다 (`POST /env-logs/photo` 가 돌려준 주소).
    # 나머지 항목은 안 보내면 그만이다.
    photo_url: str | None = Field(default=None, max_length=255)
    place: str | None = Field(default=None, max_length=100)
    # 블로그 글 주소 — **블로그만 보낸다.** 필수가 아니라, 아직 주소가 없으면
    # 안 보내고 남겨도 된다. `http(s)://` 로 시작해야 받는다.
    link: str | None = Field(default=None, max_length=500)


class EnvLogPhotoOut(CamelModel):
    """올린 사진의 저장 주소 — 이걸 [EnvLogCreate.photo_url] 에 실어 보낸다.

    **여기는 서명을 안 붙인다.** 이 값은 화면에 그리는 주소가 아니라 그대로
    DB 에 들어갈 원본 경로다. 서명(`?exp&sig`)이 붙은 채로 저장되면 7일 뒤
    만료된 주소가 영구히 남는다. 보여줄 때는 [EnvTaskLogOut.photo_url] 이
    내려가면서 서명된다.
    """

    url: str


class EnvTaskLogOut(CamelModel):
    id: str
    employee_id: str
    branch_id: str
    env_item_id: str
    item_name: str
    # 누른 순간의 기본 배점 — **가산점은 안 들어 있다** (`total_points` 를 쓸 것)
    points: int
    note: str | None = None
    # 정적 /uploads 는 안 연다 — 서명 URL(/files/..?exp&sig)로 바꿔 내려야 그린다(§H2)
    photo_url: SignedUrlOptional = None
    place: str | None = None
    link: str | None = None
    bonus_points: int = 0
    bonus_reason: str | None = None
    bonus_by_id: str | None = None
    bonus_at: datetime | None = None
    created_at: datetime

    @computed_field
    @property
    def total_points(self) -> int:
        """점수 원장에 실제로 쌓인 값 — 화면은 이걸 보여준다.

        **0 으로 바닥을 막는 것까지 라우터와 같아야 한다.** 안 맞추면 크게
        깎았을 때 원장은 0 인데 화면에는 `-47` 이 떴다 (실제로 겪었다).
        """
        return max(0, self.points + self.bonus_points)


class EnvLogAward(CamelModel):
    """대표 가산점 — 기본 배점 **위에 얹는** 값이다 (프로젝트 부여와 다르다).

    0 을 주면 가산점을 걷는다. 음수도 받는다 — 링크가 엉뚱하거나 글이 부실한데
    눌러 둔 경우에 쓴다. 다만 최종 점수는 0 아래로 안 내려간다.
    """

    points: int = Field(ge=-100, le=100)
    comment: str = Field(min_length=1, max_length=200)


class SupplyOrderCreate(CamelModel):
    branch_id: str
    item_name: str
    price: int = Field(ge=0)


class SupplyOrderOut(CamelModel):
    id: str
    branch_id: str
    item_name: str
    price: int
    ordered_by_id: str
    created_at: datetime
