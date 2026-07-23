"""JoinRequest 라우터 — 가입 승인/거절 (CLAUDE.md §2.3, [ADMIN,MANAGER])."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_role
from app.db.session import get_db
from app.enums import JoinRequestStatus, Role
from app.models.org.branch import Branch
from app.models.org.employee import Employee
from app.models.org.join_request import JoinRequest
from app.schemas.org.employee import EmployeeOut
from app.schemas.org.join_request import JoinRequestApprove, JoinRequestOut
from app.services.barcode import unique_barcode

router = APIRouter(prefix="/join-requests", tags=["join-requests"])


@router.get("", response_model=list[JoinRequestOut], dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def list_join_requests(
    db: AsyncSession = Depends(get_db),
    status: JoinRequestStatus | None = Query(None),
) -> list[JoinRequest]:
    stmt = select(JoinRequest)
    if status:
        stmt = stmt.where(JoinRequest.status == status)
    result = await db.execute(stmt.order_by(JoinRequest.created_at.desc()))
    return list(result.scalars().all())


@router.post("/{request_id}/approve", response_model=EmployeeOut, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def approve_join_request(
    request_id: str, payload: JoinRequestApprove, db: AsyncSession = Depends(get_db)
) -> Employee:
    join_request = await db.get(JoinRequest, request_id)
    if join_request is None:
        raise HTTPException(404, detail={"code": "JOIN_REQUEST_NOT_FOUND", "message": "가입 요청을 찾을 수 없습니다"})
    if join_request.status != JoinRequestStatus.PENDING:
        raise HTTPException(400, detail={"code": "ALREADY_HANDLED", "message": "이미 처리된 요청입니다"})
    if await db.get(Branch, payload.branch_id) is None:
        raise HTTPException(400, detail={"code": "BRANCH_NOT_FOUND", "message": "지점이 존재하지 않습니다"})
    if (await db.execute(select(Employee).where(Employee.email == join_request.email))).scalar_one_or_none():
        raise HTTPException(409, detail={"code": "EMAIL_TAKEN", "message": "이미 사용 중인 이메일입니다"})

    employee = Employee(
        name=join_request.name,
        email=join_request.email,
        password_hash=join_request.password_hash,
        branch_id=payload.branch_id,
        role=payload.role,
        team=payload.team,
        rank=payload.rank,
        barcode=await unique_barcode(db),
    )
    join_request.status = JoinRequestStatus.APPROVED
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return employee


@router.post("/{request_id}/reject", status_code=204, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def reject_join_request(request_id: str, db: AsyncSession = Depends(get_db)) -> None:
    join_request = await db.get(JoinRequest, request_id)
    if join_request is None:
        raise HTTPException(404, detail={"code": "JOIN_REQUEST_NOT_FOUND", "message": "가입 요청을 찾을 수 없습니다"})
    if join_request.status != JoinRequestStatus.PENDING:
        raise HTTPException(400, detail={"code": "ALREADY_HANDLED", "message": "이미 처리된 요청입니다"})
    join_request.status = JoinRequestStatus.REJECTED
    await db.commit()
    return None
