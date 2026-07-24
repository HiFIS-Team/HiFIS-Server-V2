"""회원 친절도 — 외부 웹훅 수신 + 조회 (CLAUDE.md §4.5).

POST /webhooks/kindness-survey: 앱 UI 작성 없음, 외부 폼 전용. 시크릿 검증 후 KINDNESS +10.
"""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import branch_scope, get_current_user
from app.db.session import get_db
from app.enums import ScoreCategory
from app.models.staff.employee import Employee
from app.models.scoring.kindness import KindnessSurvey
from app.schemas.scoring.kindness import KindnessSurveyOut, KindnessSurveyWebhook
from app.services.scoring import accrue_score

KINDNESS_POINTS = 10

router = APIRouter(tags=["kindness"])


async def _verify_webhook_secret(x_webhook_secret: str | None = Header(None)) -> None:
    if x_webhook_secret is None or not hmac.compare_digest(
        x_webhook_secret, settings.kindness_webhook_secret
    ):
        raise HTTPException(401, detail={"code": "INVALID_WEBHOOK_SECRET", "message": "웹훅 시크릿이 올바르지 않습니다"})


@router.post(
    "/webhooks/kindness-survey",
    response_model=KindnessSurveyOut,
    status_code=201,
    dependencies=[Depends(_verify_webhook_secret)],
)
async def receive_kindness_survey(
    payload: KindnessSurveyWebhook, db: AsyncSession = Depends(get_db)
) -> KindnessSurvey:
    if not payload.consent:
        raise HTTPException(400, detail={"code": "CONSENT_REQUIRED", "message": "개인정보 동의가 필요합니다"})
    employee = await db.get(Employee, payload.praised_employee_id)
    if employee is None:
        raise HTTPException(400, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "칭찬 대상 직원이 존재하지 않습니다"})

    survey = KindnessSurvey(
        motivation=payload.motivation,
        praised_employee_id=payload.praised_employee_id,
        praise_comment=payload.praise_comment,
        improvement=payload.improvement,
        member_name=payload.member_name,
        member_phone=payload.member_phone,
        consent=True,
    )
    db.add(survey)
    await db.flush()
    await accrue_score(
        db,
        employee_id=payload.praised_employee_id,
        branch_id=employee.branch_id,
        category=ScoreCategory.KINDNESS,
        points=KINDNESS_POINTS,
        source_ref_id=survey.id,
        reason="회원 친절도 칭찬",
    )
    await db.commit()
    await db.refresh(survey)
    return survey


@router.get("/kindness-surveys", response_model=list[KindnessSurveyOut], dependencies=[Depends(get_current_user)])
async def list_kindness_surveys(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    praised_employee_id: str | None = Query(None, alias="praisedEmployeeId"),
) -> list[KindnessSurvey]:
    stmt = select(KindnessSurvey)
    if scope:
        stmt = stmt.join(Employee, Employee.id == KindnessSurvey.praised_employee_id).where(
            Employee.branch_id == scope
        )
    if praised_employee_id:
        stmt = stmt.where(KindnessSurvey.praised_employee_id == praised_employee_id)
    result = await db.execute(stmt.order_by(KindnessSurvey.submitted_at.desc()))
    return list(result.scalars().all())
