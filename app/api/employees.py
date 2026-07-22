"""Employee 라우터 — CLAUDE.md §2.2.

주의: /me 경로는 /{employee_id} 보다 먼저 정의 (라우팅 우선순위).
TODO(멀티테넌시): 목록을 요청자 소속 지점으로 필터 (§0 지점 스코프).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.enums import EmployeeStatus, Role
from app.models.branch import Branch
from app.models.employee import Employee
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeMeUpdate,
    EmployeeOut,
    EmployeeUpdate,
    PasswordChange,
)

router = APIRouter(prefix="/employees", tags=["employees"])


async def _get_branch_or_400(db: AsyncSession, branch_id: str) -> Branch:
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(400, detail={"code": "BRANCH_NOT_FOUND", "message": "지점이 존재하지 않습니다"})
    return branch


@router.get("", response_model=list[EmployeeOut], dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def list_employees(
    db: AsyncSession = Depends(get_db),
    branch_id: str | None = Query(None, alias="branchId"),
    status: EmployeeStatus | None = Query(None),
    role: Role | None = Query(None),
    team: str | None = Query(None),
    q: str | None = Query(None),
) -> list[Employee]:
    stmt = select(Employee).where(Employee.deleted_at.is_(None))
    if branch_id:
        stmt = stmt.where(Employee.branch_id == branch_id)
    if status:
        stmt = stmt.where(Employee.status == status)
    if role:
        stmt = stmt.where(Employee.role == role)
    if team:
        stmt = stmt.where(Employee.team == team)
    if q:
        stmt = stmt.where(Employee.name.ilike(f"%{q}%"))
    result = await db.execute(stmt.order_by(Employee.created_at))
    return list(result.scalars().all())


@router.get("/me", response_model=EmployeeOut)
async def get_me(user: Employee = Depends(get_current_user)) -> Employee:
    return user


@router.patch("/me", response_model=EmployeeOut)
async def update_me(
    payload: EmployeeMeUpdate,
    user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Employee:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/me/password", status_code=204)
async def change_my_password(
    payload: PasswordChange,
    user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, detail={"code": "INVALID_PASSWORD", "message": "현재 비밀번호가 올바르지 않습니다"})
    user.password_hash = hash_password(payload.new_password)
    await db.commit()
    return None


@router.get("/{employee_id}", response_model=EmployeeOut)
async def get_employee(
    employee_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Employee:
    if current.role not in (Role.ADMIN, Role.MANAGER) and current.id != employee_id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "권한이 없습니다"})
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.deleted_at is not None:
        raise HTTPException(404, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "직원을 찾을 수 없습니다"})
    return employee


@router.post("", response_model=EmployeeOut, status_code=201, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def create_employee(payload: EmployeeCreate, db: AsyncSession = Depends(get_db)) -> Employee:
    exists = await db.execute(select(Employee).where(Employee.email == payload.email))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(409, detail={"code": "EMAIL_TAKEN", "message": "이미 사용 중인 이메일입니다"})
    await _get_branch_or_400(db, payload.branch_id)
    employee = Employee(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        branch_id=payload.branch_id,
        rank=payload.rank,
        role=payload.role,
        team=payload.team,
        phone=payload.phone,
        avatar_color=payload.avatar_color or "#6366f1",
    )
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return employee


@router.patch("/{employee_id}", response_model=EmployeeOut, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def update_employee(
    employee_id: str, payload: EmployeeUpdate, db: AsyncSession = Depends(get_db)
) -> Employee:
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.deleted_at is not None:
        raise HTTPException(404, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "직원을 찾을 수 없습니다"})
    data = payload.model_dump(exclude_unset=True)
    if data.get("branch_id"):
        await _get_branch_or_400(db, data["branch_id"])
    for key, value in data.items():
        setattr(employee, key, value)
    await db.commit()
    await db.refresh(employee)
    return employee


@router.delete("/{employee_id}", status_code=204, dependencies=[Depends(require_role(Role.ADMIN))])
async def delete_employee(employee_id: str, db: AsyncSession = Depends(get_db)) -> None:
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.deleted_at is not None:
        raise HTTPException(404, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "직원을 찾을 수 없습니다"})
    employee.deleted_at = datetime.now(timezone.utc)  # 소프트 삭제
    await db.commit()
    return None
