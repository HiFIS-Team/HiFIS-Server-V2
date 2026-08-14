"""InviteKey 라우터 — CLAUDE.md §2.3 ([ADMIN,MANAGER])."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.enums import Role, role_at_least
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.models.auth.invite import InviteKey
from app.schemas.auth.invite import InviteKeyCreate, InviteKeyOut

router = APIRouter(prefix="/invite-keys", tags=["invite-keys"])


@router.get("", response_model=list[InviteKeyOut], dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def list_invite_keys(db: AsyncSession = Depends(get_db)) -> list[InviteKey]:
    result = await db.execute(select(InviteKey).order_by(InviteKey.created_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=InviteKeyOut, status_code=201)
async def create_invite_key(
    payload: InviteKeyCreate,
    current: Employee = Depends(require_role(Role.ADMIN, Role.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> InviteKey:
    if await db.get(Branch, payload.branch_id) is None:
        raise HTTPException(400, detail={"code": "BRANCH_NOT_FOUND", "message": "지점이 존재하지 않습니다"})
    # 권한 상승 차단 — 본인보다 높은 권한의 초대키는 발급 불가 (MANAGER→ADMIN·ADMIN→MASTER 등)
    if not role_at_least(current.role, payload.role):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인보다 높은 권한의 초대키는 발급할 수 없습니다"})
    # 코드는 **서버가 만든다** — 요청자가 못 정한다 (2026-08-14, InviteKeyCreate 주석 참고).
    # 16진수 8자 = 약 43억 가지. 그래도 겹칠 수는 있으니 몇 번 다시 뽑는다.
    for _ in range(5):
        code = f"HIFIS-{uuid.uuid4().hex[:8].upper()}"
        if (await db.execute(select(InviteKey).where(InviteKey.code == code))).scalar_one_or_none() is None:
            break
    else:
        raise HTTPException(409, detail={"code": "CODE_TAKEN", "message": "초대 코드를 만들지 못했습니다. 다시 시도해주세요"})
    expires_at = payload.expires_at or datetime.now(timezone.utc) + timedelta(days=14)
    key = InviteKey(
        code=code,
        branch_id=payload.branch_id,
        role=payload.role,
        rank=payload.rank,
        employment_type=payload.employment_type,
        team=payload.team,
        issued_by_id=current.id,
        expires_at=expires_at,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


@router.delete("/{key_id}", status_code=204, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def delete_invite_key(key_id: str, db: AsyncSession = Depends(get_db)) -> None:
    key = await db.get(InviteKey, key_id)
    if key is None:
        raise HTTPException(404, detail={"code": "INVITE_KEY_NOT_FOUND", "message": "초대키를 찾을 수 없습니다"})
    await db.delete(key)
    await db.commit()
    return None
