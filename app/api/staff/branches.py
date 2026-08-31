"""Branch 라우터 — CLAUDE.md §2.1 (GET=로그인한 전원, POST/PATCH=[ADMIN]).

조회를 전원에게 연 이유: 사람·업무 데이터가 전부 branch_id 로만 오기 때문에
**지점 이름을 붙이려면 누구나 이 목록이 필요하다** (조직도 카드의 소속,
사내톡 상대 소속 등). 이름 자체는 약관에 공개된 값이라 가릴 것이 없다.
만들기·고치기는 그대로 ADMIN 전용이다.
"""


from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tokens import public_token
from app.core.deps import get_current_user, require_role
from app.core.ratelimit import client_key
from app.db.session import get_db
from app.enums import Role
from app.models.staff.branch import Branch
from app.schemas.base import CamelModel
from app.schemas.staff.branch import BranchCreate, BranchOut, BranchUpdate

router = APIRouter(prefix="/branches", tags=["branches"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "BRANCH_NOT_FOUND", "message": "지점을 찾을 수 없습니다"})


@router.get("", response_model=list[BranchOut], dependencies=[Depends(get_current_user)])
async def list_branches(db: AsyncSession = Depends(get_db)) -> list[Branch]:
    result = await db.execute(select(Branch).order_by(Branch.created_at))
    return list(result.scalars().all())


@router.post("", response_model=BranchOut, status_code=201, dependencies=[Depends(require_role(Role.ADMIN))])
async def create_branch(payload: BranchCreate, db: AsyncSession = Depends(get_db)) -> Branch:
    branch = Branch(name=payload.name, type=payload.type)
    db.add(branch)
    await db.commit()
    await db.refresh(branch)
    return branch


@router.get("/{branch_id}", response_model=BranchOut, dependencies=[Depends(get_current_user)])
async def get_branch(branch_id: str, db: AsyncSession = Depends(get_db)) -> Branch:
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise _not_found()
    return branch


class SurveyLinkOut(CamelModel):
    branch_name: str
    url: str


#: 어느 화면의 주소인가 — (URL 앞자리, 토큰을 담은 컬럼 이름)
_LINKS = {"survey": "survey_token", "tv": "tv_token", "history": "history_token"}


async def _link(branch: Branch, kind: str, db: AsyncSession, *, reset: bool) -> SurveyLinkOut:
    """지점의 공개 주소를 만들어 준다 — 없거나 [reset] 이면 새로 발급한다."""
    field = _LINKS[kind]
    if reset or not getattr(branch, field):
        setattr(branch, field, public_token())
        await db.commit()
        await db.refresh(branch)
    base = settings.public_base_url.rstrip("/")
    return SurveyLinkOut(branch_name=branch.name, url=f"{base}/{kind}/{getattr(branch, field)}")


async def _branch_or_404(branch_id: str, db: AsyncSession) -> Branch:
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise _not_found()
    return branch


@router.get("/{branch_id}/survey-link", response_model=SurveyLinkOut)
async def branch_survey_link(
    branch_id: str,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SurveyLinkOut:
    """매장에 붙일 회원 설문 QR 주소 — **MASTER·ADMIN 만**.

    토큰이 곧 그 지점 설문의 열쇠라, 전 직원에게 보이면 아무나 대신 낼 수 있다.
    """
    return await _link(await _branch_or_404(branch_id, db), "survey", db, reset=False)


@router.post("/{branch_id}/survey-link/reset", response_model=SurveyLinkOut)
async def reset_branch_survey_link(
    branch_id: str,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SurveyLinkOut:
    """설문 주소를 새로 발급한다 — **옛 QR 은 그 즉시 안 열린다.**

    토큰을 지점 id 가 아니라 따로 둔 이유가 이것이다. 주소가 새어 나가
    엉뚱한 설문이 쌓이면 여기서 갈아 끼우고 QR 만 다시 뽑아 붙이면 된다.
    """
    return await _link(await _branch_or_404(branch_id, db), "survey", db, reset=True)


@router.get("/{branch_id}/tv-link", response_model=SurveyLinkOut)
async def branch_tv_link(
    branch_id: str,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SurveyLinkOut:
    """매장 TV 에 띄울 주소 — **MASTER·ADMIN 만**.

    TV 브라우저를 전체화면으로 열어 두면 해결된 컴플레인이 돌아간다.
    **설문 주소와 다른 토큰이다** — 설문 쪽은 글을 쓰는 열쇠라 벽에 띄우면 안 된다.
    """
    return await _link(await _branch_or_404(branch_id, db), "tv", db, reset=False)


@router.post("/{branch_id}/tv-link/reset", response_model=SurveyLinkOut)
async def reset_branch_tv_link(
    branch_id: str,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SurveyLinkOut:
    return await _link(await _branch_or_404(branch_id, db), "tv", db, reset=True)


@router.patch("/{branch_id}", response_model=BranchOut, dependencies=[Depends(require_role(Role.ADMIN))])
async def update_branch(
    branch_id: str, payload: BranchUpdate, db: AsyncSession = Depends(get_db)
) -> Branch:
    branch = await db.get(Branch, branch_id)
    if branch is None:
        raise _not_found()
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(branch, key, value)
    await db.commit()
    await db.refresh(branch)
    return branch


@router.get("/{branch_id}/history-link", response_model=SurveyLinkOut)
async def branch_history_link(
    branch_id: str,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SurveyLinkOut:
    """출석 이력 주소 — **MASTER·ADMIN 만** (2026-08-26).

    이 주소를 열면 **회원 이름·전화·출석일이 줄줄이** 나온다. 매장 벽에 붙이는
    설문·TV 주소와 성격이 다르다 — 직원이 보는 자리다.

    브로제이를 쓰는 지점이 화순뿐이라 다른 지점은 주소를 만들어도
    `/history/{token}` 에서 막힌다 (`settings.broj_branch_name`).
    """
    return await _link(await _branch_or_404(branch_id, db), "history", db, reset=False)


@router.post("/{branch_id}/history-link/reset", response_model=SurveyLinkOut)
async def reset_branch_history_link(
    branch_id: str,
    _: Role = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> SurveyLinkOut:
    """새로 발급 — **옛 주소는 그 즉시 안 열린다.**"""
    return await _link(await _branch_or_404(branch_id, db), "history", db, reset=True)


# ---------- 출퇴근 QR (2026-08-28) ----------
class ScanQrOut(CamelModel):
    """카운터에 붙일 QR 과, 지금 등록된 매장 IP."""

    branch_name: str
    #: QR 에 넣을 글자 — `HIFIS-SCAN:<지점>:<시크릿>`
    payload: str
    #: 이 지점 인터넷으로 인정하는 공인 IP 들
    allowed_ips: list[str]


@router.get("/{branch_id}/scan-qr", response_model=ScanQrOut)
async def branch_scan_qr(
    branch_id: str,
    _: Role = Depends(require_role(Role.MASTER)),
    db: AsyncSession = Depends(get_db),
) -> ScanQrOut:
    """카운터에 붙일 출퇴근 QR — **MASTER 만**.

    이 값이 그 지점 QR 의 전부라, 보는 사람이 곧 QR 을 만들 수 있는 사람이다.
    매장 IP 가 한 겹 더 막지만 그건 매장 안까지의 이야기라, 발급은 좁게 둔다.
    """
    branch = await _branch_or_404(branch_id, db)
    if not branch.scan_secret:
        branch.scan_secret = public_token()
        await db.commit()
        await db.refresh(branch)
    return ScanQrOut(
        branch_name=branch.name,
        payload=f"HIFIS-SCAN:{branch.id}:{branch.scan_secret}",
        allowed_ips=list(branch.allowed_ips or []),
    )


@router.post("/{branch_id}/scan-ip", response_model=ScanQrOut)
async def register_branch_scan_ip(
    request: Request,
    branch_id: str,
    _: Role = Depends(require_role(Role.MASTER)),
    db: AsyncSession = Depends(get_db),
) -> ScanQrOut:
    """**지금 이 요청이 온 IP** 를 그 지점 인터넷으로 등록한다 — MASTER 만.

    대표가 지점에 가서 매장 와이파이에 붙은 채 한 번 누르면 된다. 회선이
    동적이라 IP 가 바뀌면 그날 아무도 QR 을 못 찍으니, 그때 다시 누른다.
    **값을 손으로 적게 하지 않는다** — 공인 IP 를 알아내는 것부터가 일이다.

    이미 있으면 그대로 둔다 (여러 번 눌러도 목록이 안 늘어난다).
    """
    branch = await _branch_or_404(branch_id, db)
    ip = client_key(request)
    ips = list(branch.allowed_ips or [])
    if ip not in ips:
        # **갈아 끼우지 않고 더한다.** 유선·무선이 다른 회선으로 나가는 지점이
        # 있어서, 새로 누를 때마다 앞의 것을 지우면 한쪽이 계속 막힌다.
        ips.append(ip)
        branch.allowed_ips = ips
        await db.commit()
        await db.refresh(branch)
    return ScanQrOut(
        branch_name=branch.name,
        payload=f"HIFIS-SCAN:{branch.id}:{branch.scan_secret or ''}",
        allowed_ips=list(branch.allowed_ips or []),
    )


@router.delete("/{branch_id}/scan-ip", response_model=ScanQrOut)
async def forget_branch_scan_ip(
    branch_id: str,
    ip: str = Query(..., description="지울 IP"),
    _: Role = Depends(require_role(Role.MASTER)),
    db: AsyncSession = Depends(get_db),
) -> ScanQrOut:
    """등록된 매장 IP 하나를 지운다 — 회선을 바꿨을 때 옛 IP 를 걷는다."""
    branch = await _branch_or_404(branch_id, db)
    branch.allowed_ips = [x for x in (branch.allowed_ips or []) if x != ip]
    await db.commit()
    await db.refresh(branch)
    return ScanQrOut(
        branch_name=branch.name,
        payload=f"HIFIS-SCAN:{branch.id}:{branch.scan_secret or ''}",
        allowed_ips=list(branch.allowed_ips or []),
    )
