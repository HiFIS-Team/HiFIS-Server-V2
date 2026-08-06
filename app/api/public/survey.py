"""회원 친절도 설문 — 매장 QR 로 들어오는 **로그인 없는** 페이지.

지점마다 QR 이 하나씩이고, 그 지점 사람만 칭찬 대상으로 뜬다.
QR 이 담는 값은 `branches.survey_token` 이다 (지점 id 가 아니다 — 새면 갈아 끼운다).

**로그인이 없다는 게 이 파일의 전부다.** 그래서 두 가지를 지킨다.

1. 직원 정보는 **이름·직급·아바타색만** 내준다. 이메일·연락처·권한·사번은 안 나간다
2. 대상 직원이 **그 지점의 MEMBER·MANAGER 인지** 서버가 다시 확인한다.
   브라우저가 보내는 id 를 그대로 믿으면 남의 지점 사람에게 점수를 줄 수 있다

기존 `POST /webhooks/kindness-survey`(시크릿 헤더)는 그대로 둔다 — 외부 폼용이고,
이 길은 브라우저에서 직접 부르는 자리라 헤더에 시크릿을 둘 수 없다.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

_PAGE = Path(__file__).resolve().parent.parent.parent / "web" / "survey.html"


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


@router.get("/survey/{token}", response_class=HTMLResponse, include_in_schema=False)
async def survey_page(token: str, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    """설문 화면 — 지점이 맞는지만 보고 HTML 을 그대로 내려준다.

    명단은 페이지가 뜬 뒤 따로 받아 간다 (아래 `/staff`). 한 파일이라
    지점 이름을 끼워 넣지 않고, 화면이 스스로 채운다.
    """
    await _branch_of(token, db)
    # 잘못된 주소면 위에서 404 다 — 여기 오면 QR 이 맞는 것이다
    return HTMLResponse(_PAGE.read_text(encoding="utf-8"))


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
