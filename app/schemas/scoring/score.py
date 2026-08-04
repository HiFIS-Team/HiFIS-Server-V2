"""ScoreEvent DTO — CLAUDE.md §4.1."""

from datetime import datetime

from pydantic import Field

from app.enums import ScoreCategory
from app.schemas.base import CamelModel


class ScoreCreate(CamelModel):
    employee_id: str
    category: ScoreCategory = ScoreCategory.OPERATOR  # 운영자 직접 부여/감점
    points: int  # 음수 = 감점/취소
    reason: str | None = None
    period: str | None = None  # 없으면 현재 기간


class ScoreEventOut(CamelModel):
    id: str
    employee_id: str
    branch_id: str
    category: ScoreCategory
    points: int
    reason: str | None = None
    source_ref_id: str | None = None
    period: str
    created_by_id: str | None = None
    created_at: datetime


class RankingItem(CamelModel):
    rank: int
    employee_id: str
    name: str
    points: int


class RankingBoardItem(CamelModel):
    """랭킹 화면이 사람마다 보여주는 한 줄.

    앱은 이 값들로 항목별 순위를 직접 세운다 — 서버가 탭마다 따로 주면
    같은 사람의 값이 탭마다 어긋날 수 있다.
    """

    employee_id: str
    name: str
    branch_id: str

    # 매출 — 그 달 등록권 결제액과 신규/재등록 건수
    revenue: int = 0
    new_signups: int = 0
    re_signups: int = 0

    # 친절 — 점수(원장 합)와 리뷰 수·별점 평균
    kindness: int = 0
    reviews: int = 0
    stars: float = 0.0

    # 프로젝트 — 점수(원장 합)와 그 달 기한인 것 중 담당분
    project_score: int = 0
    project_done: int = 0
    project_total: int = 0

    # 환경정비 — 점수(원장 합)와 수행 횟수
    care_score: int = 0
    care: int = 0

    # 수업 — 그 달 수행한 세션 수와 그것으로 쌓인 점수
    lessons: int = 0
    lesson_score: int = 0

    # 지난달 순위 — [매출, 친절, 프로젝트, 환경, 수업, 종합]. 0 이면 순위 없음
    last_rank: list[int] = Field(default_factory=lambda: [0, 0, 0, 0, 0, 0])


class ScoreSummary(CamelModel):
    employee_id: str
    period: str | None = None
    total: int
    by_category: dict[str, int]
