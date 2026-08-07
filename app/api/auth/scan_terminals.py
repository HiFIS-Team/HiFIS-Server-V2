"""ScanTerminal 라우터 — 지점 출퇴근 단말 발급·폐기 ([MASTER]).

**MASTER 만 만질 수 있다.** 이 토큰은 사람 없이 근태를 찍는 자격이라,
모니터링(74번)·동료평가 현황(33번)과 같은 종류의 판단이 필요한 자리다.
"""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import hash_terminal_token, require_role
from app.db.session import get_db
from app.enums import Role
from app.models.auth.scan_terminal import ScanTerminal
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.schemas.auth.scan_terminal import (
    ScanTerminalCreate,
    ScanTerminalCreated,
    ScanTerminalOut,
)

router = APIRouter(prefix="/scan-terminals", tags=["scan-terminals"])


@router.get(
    "",
    response_model=list[ScanTerminalOut],
    dependencies=[Depends(require_role(Role.MASTER))],
)
async def list_scan_terminals(db: AsyncSession = Depends(get_db)) -> list[ScanTerminal]:
    """폐기한 것도 같이 준다 — 언제 무엇을 껐는지가 남아야 한다."""
    result = await db.execute(
        select(ScanTerminal).order_by(ScanTerminal.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=ScanTerminalCreated, status_code=201)
async def create_scan_terminal(
    payload: ScanTerminalCreate,
    current: Employee = Depends(require_role(Role.MASTER)),
    db: AsyncSession = Depends(get_db),
) -> ScanTerminalCreated:
    """단말을 만들고 **토큰을 한 번만** 돌려준다.

    서버는 해시만 들고 있어서 다시는 못 보여준다. 놓치면 폐기하고 새로 발급한다.
    """
    if await db.get(Branch, payload.branch_id) is None:
        raise HTTPException(
            400, detail={"code": "BRANCH_NOT_FOUND", "message": "지점이 존재하지 않습니다"}
        )

    # 사람이 옮겨 적을 일이 없어서(파일에 붙여 넣는다) 길게 잡는다
    token = f"hifis_term_{secrets.token_urlsafe(32)}"
    terminal = ScanTerminal(
        branch_id=payload.branch_id,
        name=payload.name,
        token_hash=hash_terminal_token(token),
        issued_by_id=current.id,
    )
    db.add(terminal)
    await db.commit()
    await db.refresh(terminal)
    return ScanTerminalCreated(
        **ScanTerminalOut.model_validate(terminal).model_dump(), token=token
    )


@router.post(
    "/{terminal_id}/revoke",
    response_model=ScanTerminalOut,
    dependencies=[Depends(require_role(Role.MASTER))],
)
async def revoke_scan_terminal(
    terminal_id: str, db: AsyncSession = Depends(get_db)
) -> ScanTerminal:
    """폐기 — 행은 지우지 않는다.

    지우면 그 PC 에서 무슨 일이 있었는지 되짚을 단서가 사라진다.
    """
    terminal = await db.get(ScanTerminal, terminal_id)
    if terminal is None:
        raise HTTPException(
            404, detail={"code": "TERMINAL_NOT_FOUND", "message": "단말을 찾을 수 없습니다"}
        )
    if terminal.revoked_at is None:
        terminal.revoked_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(terminal)
    return terminal
