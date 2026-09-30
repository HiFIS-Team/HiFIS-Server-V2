"""OT 신청 — **로그인 없는** 페이지가 부른다 (2026-09-28 대표 요청).

네이버 플레이스 링크·전단지 QR 로 들어온다. 주소 마지막 칸은 회원 설문과
같은 `branches.survey_token` 이다 — 지점마다 QR 하나로 설문·OT 가 갈린다.
화면은 `HiFIS-Client-V2` 가 `hifis.app/ot/{token}` 에서 그린다.

**내주는 것은 지점 이름뿐이다.** 신청 본문(이름·연락처)은 활동 기록에도
안 남긴다 (`audit.NO_PAYLOAD`).
"""

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ratelimit import limiter
from app.db.session import get_db
from app.enums import Gender
from app.models.members.ot_request import OtRequest
from app.models.staff.branch import Branch
from app.schemas.base import CamelModel, normalize_phone
from app.services.monthly_goals import today_kst
from app.services.ot_requests import notify_new

router = APIRouter(tags=["ot"])


class OtBranchOut(CamelModel):
    branch_name: str


class OtApply(CamelModel):
    """신청 본문 — 로그인이 없는 자리라 **길이 상한이 전부 필요하다.**"""

    name: str = Field(min_length=1, max_length=40)
    gender: Gender
    age: int = Field(ge=1, le=120)
    phone: str = Field(min_length=1, max_length=30)
    #: `기타` 는 적은 내용이 붙어 온다 (`기타 · …`)
    purpose: str = Field(min_length=1, max_length=200)
    visit_date: date
    start_time: time
    end_time: time
    consent: bool

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)

    @field_validator("name", "purpose")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("비어 있어요")
        return v


async def _branch_of(token: str, db: AsyncSession) -> Branch:
    branch = await db.scalar(select(Branch).where(Branch.survey_token == token))
    if branch is None:
        raise HTTPException(
            404, detail={"code": "OT_NOT_FOUND", "message": "신청 주소가 올바르지 않습니다"}
        )
    return branch


@router.get("/ot/{token}/info", response_model=OtBranchOut)
async def ot_branch(token: str, db: AsyncSession = Depends(get_db)) -> OtBranchOut:
    branch = await _branch_of(token, db)
    return OtBranchOut(branch_name=branch.name)


@router.post("/ot/{token}", status_code=201)
@limiter.limit("10/minute")  # IP당 분 10회 — 로그인 없는 자리라 도배를 막는다
async def apply_ot(
    request: Request,
    token: str,
    payload: OtApply,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    branch = await _branch_of(token, db)
    if not payload.consent:
        raise HTTPException(
            400, detail={"code": "CONSENT_REQUIRED", "message": "개인정보 수집에 동의해 주세요"}
        )
    if payload.visit_date < today_kst():
        raise HTTPException(
            400, detail={"code": "PAST_DATE", "message": "오늘 이후 날짜를 골라 주세요"}
        )
    if payload.end_time <= payload.start_time:
        raise HTTPException(
            400, detail={"code": "BAD_TIME", "message": "끝나는 시간이 시작보다 늦어야 해요"}
        )
    ot = OtRequest(
        branch_id=branch.id,
        name=payload.name,
        gender=payload.gender,
        age=payload.age,
        phone=payload.phone,
        purpose=payload.purpose,
        visit_date=payload.visit_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        consented_at=datetime.now(timezone.utc),
    )
    db.add(ot)
    # **신청을 먼저 못 박는다** — 알림이 흔들려도 손님이 낸 것이 사라지면 안 된다
    await db.commit()
    try:
        await notify_new(db, ot)
        await db.commit()
    except Exception:
        await db.rollback()
    return {"result": "OK"}
