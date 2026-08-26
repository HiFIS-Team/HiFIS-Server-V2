"""ScanTerminal 라우터 — 지점 출퇴근 단말 발급·폐기 ([MASTER]).

**MASTER 만 만질 수 있다.** 이 토큰은 사람 없이 근태를 찍는 자격이라,
모니터링(74번)·동료평가 현황(33번)과 같은 종류의 판단이 필요한 자리다.
"""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import current_terminal, hash_terminal_token, require_role
from app.db.session import get_db
from app.enums import Role
from app.models.auth.scan_terminal import ScanTerminal
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.schemas.auth.scan_terminal import (
    ScanTerminalCreate,
    ScanTerminalCreated,
    ScanTerminalHeartbeat,
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


# ---------------------------------------------------------------------------
# 생존 신호 — 단말 자신이 부른다 (사람이 아니다)
# ---------------------------------------------------------------------------
#
# 왜 필요했나: 화순에서 스캔이 통째로 안 들어온 날(2026-08-26) 서버에는 성공도
# 실패도 없었다. 요청이 안 온 것이라 **아무도 안 찍은 것과 구별이 안 됐다.**
# 그날 저녁 결근 알림이 나가면 네 명이 안 나온 것처럼 보인다.
#
# 여기 둘은 `current_terminal` 을 쓴다 — `scan_actor` 와 달리 `last_used_at`
# 을 안 민다. 같이 밀면 가르려던 뜻이 사라진다.


@router.post("/startup", status_code=204)
async def terminal_startup(
    terminal=Depends(current_terminal), db: AsyncSession = Depends(get_db)
) -> None:
    """프로그램이 떴다 — **활동 기록에 남긴다.**

    하루에 몇 번 안 오고, **자꾸 다시 뜨는 것 자체가 봐야 할 신호**라
    일부러 남긴다 (하트비트는 반대로 뺀다 — audit `SKIP`).
    """
    now = datetime.now(timezone.utc)
    terminal.started_at = now
    terminal.heartbeat_at = now
    # 막 떴을 때는 아직 포트를 안 잡았다. 옛 값을 남겨 두면 스캐너가 붙어 있는
    # 것으로 잘못 읽힌다 — 첫 하트비트가 실제 포트를 알려 준다.
    terminal.scanner_port = None
    await db.commit()


@router.post("/heartbeat", status_code=204)
async def terminal_heartbeat(
    payload: ScanTerminalHeartbeat | None = Body(default=None),
    terminal=Depends(current_terminal),
    db: AsyncSession = Depends(get_db),
) -> None:
    """5분마다 "살아 있다" — **활동 기록에 안 남긴다.**

    단말 3대면 하루 864건이라 지금 전체(하루 390건)의 두 배가 넘어
    **활동 기록 화면이 도배된다.** 열람 기록을 탭으로 가른 것과 같은 이유다.

    [scanner_port] 가 null 이면 **스캐너를 못 찾는 중**이다 — 프로그램은
    도는데 케이블이 빠졌거나 드라이버가 안 잡힌 상태.
    """
    now = datetime.now(timezone.utc)
    terminal.heartbeat_at = now
    port = payload.scanner_port if payload else None
    terminal.scanner_port = port
    if port:
        terminal.scanner_at = now
    await db.commit()
