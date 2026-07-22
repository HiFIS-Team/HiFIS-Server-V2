"""Account 라우터 — 계정 관리 (CLAUDE.md §6.7).

비번은 암호화 저장·응답 제외. 열람은 GET /{id}/secret (ADMIN|작성자) + 접근 로그.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.deps import get_current_user
from app.db.session import get_db
from app.enums import Role
from app.models.account import Account, AccountAccessLog
from app.models.employee import Employee
from app.schemas.account import AccountCreate, AccountOut, AccountSecretOut, AccountUpdate

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[Depends(get_current_user)])


def _not_found() -> HTTPException:
    return HTTPException(404, detail={"code": "ACCOUNT_NOT_FOUND", "message": "계정을 찾을 수 없습니다"})


def _require_owner_or_admin(account: Account, current: Employee) -> None:
    if current.role != Role.ADMIN and account.owner_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "작성자 또는 관리자만 가능합니다"})


@router.get("", response_model=list[AccountOut])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Query(None),
    cat: str | None = Query(None),
    q: str | None = Query(None),
) -> list[Account]:
    stmt = select(Account)
    if scope:
        stmt = stmt.where(Account.scope == scope)
    if cat:
        stmt = stmt.where(Account.cat == cat)
    if q:
        stmt = stmt.where(or_(Account.name.ilike(f"%{q}%"), Account.login_id.ilike(f"%{q}%")))
    result = await db.execute(stmt.order_by(Account.created_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=AccountOut, status_code=201)
async def create_account(
    payload: AccountCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Account:
    nonce, ciphertext = encrypt_secret(payload.password)
    account = Account(
        name=payload.name,
        cat=payload.cat,
        scope=payload.scope,
        login_id=payload.login_id,
        url=payload.url,
        owner_id=current.id,
        memo=payload.memo,
        active=payload.active,
        secret_nonce=nonce,
        secret_ciphertext=ciphertext,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(account_id: str, db: AsyncSession = Depends(get_db)) -> Account:
    account = await db.get(Account, account_id)
    if account is None:
        raise _not_found()
    return account


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: str,
    payload: AccountUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Account:
    account = await db.get(Account, account_id)
    if account is None:
        raise _not_found()
    _require_owner_or_admin(account, current)
    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        password = data.pop("password")
        account.secret_nonce, account.secret_ciphertext = encrypt_secret(password)
    for key, value in data.items():
        setattr(account, key, value)
    await db.commit()
    await db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=204)
async def delete_account(
    account_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    account = await db.get(Account, account_id)
    if account is None:
        raise _not_found()
    _require_owner_or_admin(account, current)
    await db.delete(account)
    await db.commit()
    return None


@router.get("/{account_id}/secret", response_model=AccountSecretOut)
async def get_account_secret(
    account_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountSecretOut:
    account = await db.get(Account, account_id)
    if account is None:
        raise _not_found()
    _require_owner_or_admin(account, current)  # ADMIN | 작성자
    db.add(AccountAccessLog(account_id=account.id, accessor_id=current.id))  # 접근 로그
    await db.commit()
    password = decrypt_secret(account.secret_nonce, account.secret_ciphertext)
    return AccountSecretOut(password=password)
