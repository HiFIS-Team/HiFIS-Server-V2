"""동의 이력 라우터 — 직원 약관(§12) · 회원 개인정보 수집(§13).

입증 책임이 회사 → 동의마다 시각·문서버전(회원은 서명 이미지까지) 영속화.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.storage import save_signature
from app.db.session import get_db
from app.enums import Role
from app.models.legal.consent import EmployeeConsent, MemberConsent
from app.models.members.member import Member
from app.models.staff.employee import Employee
from app.schemas.legal.consent import (
    EmployeeConsentCreate,
    EmployeeConsentOut,
    MemberConsentCreate,
    MemberConsentOut,
)

router = APIRouter(tags=["consents"], dependencies=[Depends(get_current_user)])


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")  # 프록시(Caddy/CF) 뒤 첫 홉
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


# ---------- 직원 약관 동의 (#12) ----------
@router.post("/employees/me/consents", response_model=EmployeeConsentOut, status_code=201)
async def record_my_consent(
    payload: EmployeeConsentCreate,
    request: Request,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EmployeeConsent:
    consent = EmployeeConsent(
        employee_id=current.id,
        doc_type=payload.doc_type,
        doc_version=payload.doc_version,
        ip=_client_ip(request),
    )
    db.add(consent)
    await db.commit()
    await db.refresh(consent)
    return consent


@router.get("/employees/me/consents", response_model=list[EmployeeConsentOut])
async def list_my_consents(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EmployeeConsent]:
    rows = await db.execute(
        select(EmployeeConsent)
        .where(EmployeeConsent.employee_id == current.id)
        .order_by(EmployeeConsent.agreed_at.desc())
    )
    return list(rows.scalars().all())


@router.get(
    "/employees/{employee_id}/consents",
    response_model=list[EmployeeConsentOut],
    dependencies=[Depends(require_role(Role.ADMIN))],  # 감사 — MASTER 자동 포함
)
async def list_employee_consents(
    employee_id: str, db: AsyncSession = Depends(get_db)
) -> list[EmployeeConsent]:
    rows = await db.execute(
        select(EmployeeConsent)
        .where(EmployeeConsent.employee_id == employee_id)
        .order_by(EmployeeConsent.agreed_at.desc())
    )
    return list(rows.scalars().all())


# ---------- 회원 개인정보 수집 동의 (#13) ----------
@router.post(
    "/members/{member_id}/consents",
    response_model=MemberConsentOut,
    status_code=201,
    dependencies=[Depends(require_role(Role.MEMBER, Role.MANAGER))],  # 회원 등록 주체(트레이너·점장)
)
async def record_member_consent(
    member_id: str,
    payload: MemberConsentCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MemberConsent:
    if await db.get(Member, member_id) is None:
        raise HTTPException(404, detail={"code": "MEMBER_NOT_FOUND", "message": "회원을 찾을 수 없습니다"})
    signature_url = save_signature(payload.signature_base64)  # 서명 이미지 로컬 저장(§9.2)
    consent = MemberConsent(
        member_id=member_id,
        doc_type=payload.doc_type,
        doc_version=payload.doc_version,
        signature_url=signature_url,
        collected_by_id=current.id,
    )
    db.add(consent)
    await db.commit()
    await db.refresh(consent)
    return consent


@router.get("/members/{member_id}/consents", response_model=list[MemberConsentOut])
async def list_member_consents(
    member_id: str, db: AsyncSession = Depends(get_db)
) -> list[MemberConsent]:
    if await db.get(Member, member_id) is None:
        raise HTTPException(404, detail={"code": "MEMBER_NOT_FOUND", "message": "회원을 찾을 수 없습니다"})
    rows = await db.execute(
        select(MemberConsent)
        .where(MemberConsent.member_id == member_id)
        .order_by(MemberConsent.agreed_at.desc())
    )
    return list(rows.scalars().all())
