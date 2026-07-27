"""Employee 라우터 — CLAUDE.md §2.2.

주의: /me 경로는 /{employee_id} 보다 먼저 정의 (라우팅 우선순위).
목록은 지점 스코프(§0): MEMBER=본인 지점 로스터 / MANAGER·ADMIN=전체.
"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.core.periods import KST
from app.core.security import hash_password, verify_password
from app.core.storage import save_avatar
from app.db.session import get_db
from app.enums import EmployeeStatus, Role
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.schemas.staff.employee import (
    EmployeeCreate,
    EmployeeMeUpdate,
    EmployeeOut,
    EmployeeUpdate,
    PasswordChange,
    ScheduleSet,
)
from app.services.employee_codes import unique_emp_no

router = APIRouter(prefix="/employees", tags=["employees"])


async def _get_branch_or_400(db: AsyncSession, branch_id: str) -> Branch:
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(400, detail={"code": "BRANCH_NOT_FOUND", "message": "지점이 존재하지 않습니다"})
    return branch


@router.get("", response_model=list[EmployeeOut], dependencies=[Depends(get_current_user)])
async def list_employees(
    db: AsyncSession = Depends(get_db),
    branch_id: str | None = Query(None, alias="branchId"),
    status: EmployeeStatus | None = Query(None),
    role: Role | None = Query(None),
    team: str | None = Query(None),
    q: str | None = Query(None),
) -> list[Employee]:
    # 직원 명단은 '전사 인원 디렉터리'(전 지점) — 프로젝트 담당자·회의 참석자·멘션·랭킹 등
    # 인원 지정에 다른 지점 사람도 보여야 한다. (지점 업무 데이터가 아니라 '사람'이므로 지점 제한 없음.
    #  민감 데이터(회원·급여·점수원장 등)는 각 도메인에서 별도 지점 스코프.)
    # 특정 지점만 보고 싶으면 branchId 로 필터.
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


@router.post("/me/schedule", response_model=EmployeeOut)
async def set_my_schedule(
    payload: ScheduleSet,
    user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Employee:
    """기본 근무 시간 설정·수정 — 근무외출근 자동 판정 기준. 최초는 온보딩 가이드, 이후 근태 화면에서 변경.

    ⚠️ 이미 설정돼 있고 **지금이 본인 근무 시간 중(shift_start~shift_end)** 이면 변경 불가(403 WITHIN_SHIFT).
    근무 중 종료 시각을 당겨 초과근무 점수를 만드는 파밍 방지 — 근무 시간 밖에서만 수정.
    """
    if payload.shift_end <= payload.shift_start:
        raise HTTPException(400, detail={"code": "INVALID_RANGE", "message": "퇴근 시간이 출근 시간보다 늦어야 합니다"})
    if user.shift_start is not None and user.shift_end is not None:
        now = datetime.now(timezone.utc).astimezone(KST)
        now_min = now.hour * 60 + now.minute
        sh, sm = user.shift_start.split(":")
        eh, em = user.shift_end.split(":")
        if int(sh) * 60 + int(sm) <= now_min <= int(eh) * 60 + int(em):
            raise HTTPException(403, detail={"code": "WITHIN_SHIFT", "message": "근무 시간 중에는 근무 시간을 변경할 수 없습니다"})
    user.shift_start = payload.shift_start
    user.shift_end = payload.shift_end
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
    user.token_version += 1  # 비번 변경 → 기존 세션 전부 무효화(§M2)
    await db.commit()
    return None


def _remove_local(url: str | None) -> None:
    if url and url.startswith("/uploads/"):
        path = url.lstrip("/")
        if os.path.exists(path):
            os.remove(path)


@router.post("/me/avatar", response_model=EmployeeOut)
async def upload_my_avatar(
    file: UploadFile = File(...),
    user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Employee:
    old = user.avatar_url
    user.avatar_url = await save_avatar(file)
    await db.commit()
    await db.refresh(user)
    _remove_local(old)  # 이전 아바타 파일 정리
    return user


@router.post("/me/withdraw", status_code=204)
async def withdraw_me(
    user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """본인 탈퇴 — 소프트삭제 + 익명화. 근태·급여 등 기록은 row 유지로 보존."""
    if user.deleted_at is not None:
        raise HTTPException(400, detail={"code": "ALREADY_WITHDRAWN", "message": "이미 탈퇴한 계정입니다"})
    if user.role == Role.ADMIN:  # 마지막 관리자는 탈퇴 불가
        other_admins = await db.scalar(
            select(func.count()).select_from(Employee).where(
                Employee.role == Role.ADMIN,
                Employee.deleted_at.is_(None),
                Employee.id != user.id,
            )
        )
        if not other_admins:
            raise HTTPException(409, detail={"code": "LAST_ADMIN", "message": "다른 관리자가 있어야 탈퇴할 수 있습니다"})

    old_avatar = user.avatar_url
    user.name = "(탈퇴한 직원)"
    user.email = f"withdrawn.{user.id}@removed.local"  # 원래 이메일 해방(재가입 가능)
    user.phone = None
    user.avatar_url = None
    user.status_message = None
    # emp_no 는 유지(비PII 식별자). deleted_at 세팅으로 스캔은 자동 제외됨
    user.status = EmployeeStatus.RESIGNED
    user.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    _remove_local(old_avatar)
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
        emp_no=await unique_emp_no(db),
    )
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return employee


@router.patch("/{employee_id}", response_model=EmployeeOut, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def update_employee(
    employee_id: str,
    payload: EmployeeUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Employee:
    employee = await db.get(Employee, employee_id)
    if employee is None or employee.deleted_at is not None:
        raise HTTPException(404, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "직원을 찾을 수 없습니다"})
    data = payload.model_dump(exclude_unset=True)
    # 권한 상승 방지: ADMIN 권한을 주거나 ADMIN 계정을 수정하는 건 ADMIN 만 (MANAGER 셀프승격 차단)
    if current.role != Role.ADMIN and (data.get("role") == Role.ADMIN or employee.role == Role.ADMIN):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "ADMIN 권한 변경은 관리자만 가능합니다"})
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
