"""회원이 보는 수업 화면 DTO — `hifis.app/training/{token}` (로그인 없음).

**여기 있는 것이 곧 밖으로 나가는 것 전부다.** 회원 스스로 보는 화면이라
자기 이름과 자기 운동 기록만 담는다 — 전화번호·회원 id·트레이너 id·지점 id·
결제 금액·남은 회차는 한 칸도 안 나간다 (주소가 새면 그대로 새는 값이다).
"""

from datetime import date

from pydantic import Field

from app.enums import WorkoutKind
from app.schemas.base import CamelModel
from app.schemas.members.workout import (
    MAX_GROUPS,
    MAX_ROWS,
    CardioRow,
    MediaGroupIn,
    MediaGroupOut,
    WeightRow,
)


class TrainingLogOut(CamelModel):
    """일지 한 장 — `WorkoutLogOut` 에서 회원이 볼 이유가 없는 칸을 뺐다.

    `member_id`·`author_id` 가 없다. 화면에 안 쓰는데 내보내면 다른 API 를
    두드려 볼 재료만 준다.
    """

    id: str
    kind: WorkoutKind
    session_no: int | None = None
    title: str
    performed_on: date
    weights: list[WeightRow] = Field(default_factory=list)
    cardio: list[CardioRow] = Field(default_factory=list)
    media: list[MediaGroupOut] = Field(default_factory=list)
    #: 개인 운동에 트레이너가 단 총평 — 회원은 읽기만 한다
    trainer_feedback: str | None = None
    #: 회원이 직접 쓴 줄인가 — 웹에서 고칠 수 있는 것만 참이다
    mine: bool = False


class TrainingPageOut(CamelModel):
    member_name: str
    trainer_name: str
    #: 운동을 하는 이유 — 트레이너가 상담에서 받아 적은 줄
    goals: list[str] = Field(default_factory=list)
    pt: list[TrainingLogOut] = Field(default_factory=list)
    personal: list[TrainingLogOut] = Field(default_factory=list)


class PersonalLogIn(CamelModel):
    """회원이 웹에서 적는 개인 운동.

    **`trainer_feedback` 칸이 없다.** 그건 트레이너가 앱에서 다는 말이라,
    받는 자리에 두면 회원이 자기 칭찬을 써 넣을 수 있다.
    """

    title: str = Field(max_length=100)
    performed_on: date
    weights: list[WeightRow] = Field(default_factory=list, max_length=MAX_ROWS)
    cardio: list[CardioRow] = Field(default_factory=list, max_length=MAX_ROWS)
    media: list[MediaGroupIn] = Field(default_factory=list, max_length=MAX_GROUPS)
