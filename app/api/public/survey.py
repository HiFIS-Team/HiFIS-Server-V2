"""회원 친절도 설문 — 매장 QR 로 들어오는 **로그인 없는** 페이지.

지점마다 QR 이 하나씩이고, 그 지점 사람만 칭찬 대상으로 뜬다.
QR 이 담는 값은 `branches.survey_token` 이다 (지점 id 가 아니다 — 새면 갈아 끼운다).

**로그인이 없다는 게 이 파일의 전부다.** 그래서 두 가지를 지킨다.

1. 직원 정보는 **이름·직급·아바타색만** 내준다. 이메일·연락처·권한·사번은 안 나간다
2. 대상 직원이 **그 지점의 MEMBER·MANAGER 인지** 서버가 다시 확인한다.
   브라우저가 보내는 id 를 그대로 믿으면 남의 지점 사람에게 점수를 줄 수 있다

기존 `POST /webhooks/kindness-survey`(시크릿 헤더)는 그대로 둔다 — 외부 폼용이고,
이 길은 브라우저에서 직접 부르는 자리라 헤더에 시크릿을 둘 수 없다.

**화면은 여기서 안 그린다 (2026-08-20).** `HiFIS-Client-V2` 가 `hifis.app` 에서
그리고, 이 라우터는 값만 준다. 예전 주소로 들어오면 그쪽으로 넘긴다.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.ratelimit import limiter
from app.db.session import get_db
from app.enums import EmployeeStatus, Role, ScoreCategory
from app.models.scoring.kindness import KindnessSurvey
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.schemas.base import CamelModel
from app.services.scoring import accrue_score

from fastapi import Depends

router = APIRouter(tags=["survey"])

#: 칭찬 한 건에 붙는 점수 — `app/api/scoring/kindness.py` 와 같은 값이어야 한다
KINDNESS_POINTS = 10

#: 칭찬 대상이 될 수 있는 사람 — **현장에서 회원을 만나는 쪽**이다.
#: 세션 싸인·환경정비를 여는 기준과 같다 (대표·관리자는 운영 전담이라 뺀다).
_FIELD_ROLES = (Role.MEMBER, Role.MANAGER)


class SurveyStaffOut(CamelModel):
    """설문 페이지가 쓰는 직원 한 명 — **내줄 수 있는 것만** 담는다."""

    id: str
    name: str
    rank: str
    avatar_color: str


class SurveyBranchOut(CamelModel):
    branch_name: str
    staff: list[SurveyStaffOut]


class SurveySubmit(CamelModel):
    motivation: str
    praised_employee_id: str
    praise_comment: str
    improvement: str | None = None
    member_name: str
    member_phone: str
    consent: bool


async def _branch_of(token: str, db: AsyncSession) -> Branch:
    branch = await db.scalar(select(Branch).where(Branch.survey_token == token))
    if branch is None:
        raise HTTPException(
            404, detail={"code": "SURVEY_NOT_FOUND", "message": "설문 주소가 올바르지 않습니다"}
        )
    return branch


@router.get("/survey/{token}", include_in_schema=False)
async def survey_page(token: str) -> RedirectResponse:
    """옛 주소 — **화면이 있는 곳으로 넘긴다** (2026-08-20).

    화면을 `hifis.app` 으로 옮기면서 여기서 HTML 을 내려주는 일을 그만뒀다.
    **라우트를 안 지운다** — 이미 뽑아 붙인 QR 이 `api.hifis.app` 을 가리킬 수
    있어서다. 벽에 붙은 종이는 우리가 회수하기 전까지 그대로 살아 있다.

    **토큰이 맞는지 여기서 안 본다.** 넘어간 화면이 명단을 받아 보고 틀리면
    '설문을 열 수 없어요' 를 그린다 — 여기서 한 번 더 물어봐야 왕복만 는다.
    """
    base = settings.public_base_url.rstrip("/")
    return RedirectResponse(f"{base}/survey/{token}", status_code=308)


@router.get("/survey/{token}/staff", response_model=SurveyBranchOut)
async def survey_staff(token: str, db: AsyncSession = Depends(get_db)) -> SurveyBranchOut:
    """그 지점에서 칭찬을 받을 수 있는 사람 — 재직 중인 MEMBER·MANAGER."""
    branch = await _branch_of(token, db)
    rows = (
        await db.scalars(
            select(Employee)
            .where(
                Employee.branch_id == branch.id,
                Employee.role.in_(_FIELD_ROLES),
                Employee.status == EmployeeStatus.ACTIVE,
                Employee.deleted_at.is_(None),
            )
            .order_by(Employee.name)
        )
    ).all()
    return SurveyBranchOut(
        branch_name=branch.name,
        staff=[
            SurveyStaffOut(
                id=e.id, name=e.name, rank=e.rank.value, avatar_color=e.avatar_color
            )
            for e in rows
        ],
    )


@router.post("/survey/{token}", status_code=201)
@limiter.limit("30/minute")  # IP당 분 30회 — 웹훅과 같은 기준(§M4)
async def submit_survey(
    request: Request,
    token: str,
    payload: SurveySubmit,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """설문 접수 — 칭찬받은 직원에게 친절 점수가 붙는다.

    **같은 사람이 여러 번 내는 걸 막지 않는다** (2026-08-05 결정).
    이상하게 쌓이면 그때 보기로 했고, 지금은 IP 레이트리밋만 있다.
    """
    branch = await _branch_of(token, db)

    if not payload.consent:
        raise HTTPException(
            400, detail={"code": "CONSENT_REQUIRED", "message": "개인정보 수집 동의가 필요합니다"}
        )

    employee = await db.get(Employee, payload.praised_employee_id)
    # **브라우저가 보낸 id 를 그대로 믿지 않는다.** 지점·권한·재직을 다시 본다 —
    # 안 그러면 남의 지점 사람이나 대표에게 점수를 꽂을 수 있다
    if (
        employee is None
        or employee.deleted_at is not None
        or employee.branch_id != branch.id
        or employee.role not in _FIELD_ROLES
        or employee.status != EmployeeStatus.ACTIVE
    ):
        raise HTTPException(
            400, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "칭찬할 직원을 다시 골라주세요"}
        )

    survey = KindnessSurvey(
        motivation=payload.motivation,
        praised_employee_id=employee.id,
        praise_comment=payload.praise_comment,
        improvement=payload.improvement or None,
        member_name=payload.member_name,
        member_phone=payload.member_phone,
        consent=True,
    )
    db.add(survey)
    await db.flush()
    await accrue_score(
        db,
        employee_id=employee.id,
        branch_id=branch.id,
        category=ScoreCategory.KINDNESS,
        points=KINDNESS_POINTS,
        source_ref_id=survey.id,
        reason="회원 친절도 칭찬",
    )
    await db.commit()
    # 접수됐다는 것만 알려준다 — 설문 내용을 돌려주면 남이 남긴 것도 읽힌다
    return {"praisedName": employee.name}
