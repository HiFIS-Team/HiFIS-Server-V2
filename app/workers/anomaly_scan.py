"""이상행동 감지 — 5분마다 접속·활동 로그를 훑는다 (모니터링 '이상 징후').

로그는 낱개 사실만 남긴다. 여기서는 **묶어서 판단한다** — 로그인 실패 한 번은
오타지만 10분에 다섯 번은 다른 뜻이다.

찾으면 `anomalies` 에 남기고 **MASTER 에게 푸시**를 보낸다. 스캔이 5분마다
도는데 감지 창은 10분이라 같은 사건이 두 번 걸리므로, `window_key` 로
한 창에 한 줄만 남긴다 (중복이면 조용히 넘어간다).

새 규칙을 더할 때는 `_RULES` 에 함수를 하나 얹으면 된다.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.enums import AccessEvent, AnomalyKind, Role
from app.models.platform.access_log import AccessLog
from app.models.platform.anomaly import Anomaly
from app.models.platform.audit_log import AuditLog
from app.models.staff.employee import Employee

logger = logging.getLogger(__name__)

# 얼마나 거슬러 보나 — 스캔 주기(5분)보다 길어야 사이에 낀 것을 안 놓친다
WINDOW_MIN = 10

# 몇 번부터 이상으로 보나
LOGIN_FAIL_MIN = 5  # 로그인 실패
FORBIDDEN_MIN = 5  # 권한 없는 요청(403)
DELETE_MIN = 10  # 삭제
READ_MIN = 20  # 남의 대화·기록 열람

# 처음 보는 IP 를 가릴 때 얼마나 거슬러 보나 — 이 기간에 없던 곳이면 새 곳이다
KNOWN_IP_DAYS = 30

# 열람으로 세는 주소 — 활동 로그의 READ_LOGGED 중 '남의 것을 들여다보는' 것
_READ_ROUTES = (
    "/audit/chat/rooms",
    "/audit/chat/rooms/{id}/messages",
    "/audit/chat/messages",
)


@dataclass(frozen=True)
class Found:
    """찾아낸 한 건 — 아직 저장 전이다"""

    kind: AnomalyKind
    subject: str
    detail: str
    count: int
    employee_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    # 같은 사건을 두 번 안 만들게 하는 열쇠에 붙일 꼬리표
    key_extra: str = ""


def _slot(now: datetime) -> str:
    """감지 창을 나타내는 문자열 — 같은 10분 안이면 같은 값이다"""
    return now.strftime("%Y%m%d%H") + f"{now.minute // WINDOW_MIN:02d}"


async def _login_fails(db: AsyncSession, since: datetime) -> list[Found]:
    """브루트포스 — 같은 대상(계정 또는 IP)으로 로그인 반복 실패"""
    rows = (
        await db.execute(
            select(
                func.coalesce(AccessLog.email, AccessLog.ip).label("who"),
                func.count().label("n"),
                func.max(AccessLog.ip).label("ip"),
                func.max(AccessLog.user_agent).label("ua"),
                func.max(AccessLog.employee_id).label("eid"),
            )
            .where(AccessLog.event == AccessEvent.LOGIN_FAIL, AccessLog.created_at >= since)
            .group_by("who")
            .having(func.count() >= LOGIN_FAIL_MIN)
        )
    ).all()
    return [
        Found(
            kind=AnomalyKind.BRUTE_FORCE,
            subject=row.who or "알 수 없음",
            detail=f"{WINDOW_MIN}분 동안 로그인 {row.n}번 실패",
            count=row.n,
            employee_id=row.eid,
            ip=row.ip,
            user_agent=row.ua,
        )
        for row in rows
    ]


async def _forbidden(db: AsyncSession, since: datetime) -> list[Found]:
    """권한 없는 요청 반복 — 앱에 안 보이는 기능을 직접 부르는 것"""
    rows = (
        await db.execute(
            select(
                AuditLog.employee_id,
                func.count().label("n"),
                func.max(AuditLog.ip).label("ip"),
                func.max(AuditLog.user_agent).label("ua"),
                func.max(AuditLog.route).label("route"),
            )
            .where(
                AuditLog.status == 403,
                AuditLog.created_at >= since,
                AuditLog.employee_id.is_not(None),
            )
            .group_by(AuditLog.employee_id)
            .having(func.count() >= FORBIDDEN_MIN)
        )
    ).all()
    return [
        Found(
            kind=AnomalyKind.FORBIDDEN_BURST,
            subject=await _name(db, row.employee_id),
            detail=f"{WINDOW_MIN}분 동안 권한 없는 요청 {row.n}번 (마지막 {row.route})",
            count=row.n,
            employee_id=row.employee_id,
            ip=row.ip,
            user_agent=row.ua,
        )
        for row in rows
    ]


async def _new_device(db: AsyncSession, since: datetime) -> list[Found]:
    """처음 보는 곳에서의 로그인 — 계정 탈취 신호"""
    recent = (
        await db.execute(
            select(AccessLog)
            .where(
                AccessLog.event == AccessEvent.LOGIN_SUCCESS,
                AccessLog.created_at >= since,
                AccessLog.employee_id.is_not(None),
                AccessLog.ip.is_not(None),
            )
            .order_by(AccessLog.created_at.desc())
        )
    ).scalars().all()

    known_since = since - timedelta(days=KNOWN_IP_DAYS)
    found: list[Found] = []
    seen: set[tuple[str, str]] = set()
    for log in recent:
        pair = (log.employee_id, log.ip)
        if pair in seen:
            continue
        seen.add(pair)
        before = await db.scalar(
            select(func.count())
            .select_from(AccessLog)
            .where(
                AccessLog.employee_id == log.employee_id,
                AccessLog.ip == log.ip,
                AccessLog.event == AccessEvent.LOGIN_SUCCESS,
                AccessLog.created_at >= known_since,
                AccessLog.created_at < since,
            )
        )
        if before:
            continue  # 원래 쓰던 곳이다
        found.append(
            Found(
                kind=AnomalyKind.NEW_DEVICE,
                subject=await _name(db, log.employee_id),
                detail=f"{KNOWN_IP_DAYS}일간 안 쓰던 곳에서 로그인 ({log.ip})",
                count=1,
                employee_id=log.employee_id,
                ip=log.ip,
                user_agent=log.user_agent,
                key_extra=log.ip or "",
            )
        )
    return found


async def _bursts(db: AsyncSession, since: datetime) -> list[Found]:
    """짧은 시간에 대량 삭제 · 남의 대화 열람 급증"""
    found: list[Found] = []
    for kind, condition, floor, label in (
        (AnomalyKind.BULK_DELETE, AuditLog.method == "DELETE", DELETE_MIN, "삭제"),
        (AnomalyKind.READ_BURST, AuditLog.route.in_(_READ_ROUTES), READ_MIN, "남의 대화 열람"),
    ):
        rows = (
            await db.execute(
                select(
                    AuditLog.employee_id,
                    func.count().label("n"),
                    func.max(AuditLog.ip).label("ip"),
                    func.max(AuditLog.user_agent).label("ua"),
                )
                .where(
                    condition,
                    AuditLog.status < 400,
                    AuditLog.created_at >= since,
                    AuditLog.employee_id.is_not(None),
                )
                .group_by(AuditLog.employee_id)
                .having(func.count() >= floor)
            )
        ).all()
        for row in rows:
            found.append(
                Found(
                    kind=kind,
                    subject=await _name(db, row.employee_id),
                    detail=f"{WINDOW_MIN}분 동안 {label} {row.n}번",
                    count=row.n,
                    employee_id=row.employee_id,
                    ip=row.ip,
                    user_agent=row.ua,
                )
            )
    return found


_RULES = (_login_fails, _forbidden, _new_device, _bursts)


async def _name(db: AsyncSession, employee_id: str | None) -> str:
    if employee_id is None:
        return "알 수 없음"
    employee = await db.get(Employee, employee_id)
    return employee.name if employee else "알 수 없음"


async def anomaly_scan() -> None:
    """5분마다 — 찾고, 남기고, 대표에게 알린다"""
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=WINDOW_MIN)
    slot = _slot(now)

    async with SessionLocal() as db:
        found: list[Found] = []
        for rule in _RULES:
            try:
                found.extend(await rule(db, since))
            except Exception:  # 규칙 하나가 터져도 나머지는 돌아야 한다
                logger.exception("이상행동 규칙 실패: %s", rule.__name__)

        if not found:
            return

        masters = (
            await db.execute(
                select(Employee.id).where(
                    Employee.role == Role.MASTER, Employee.deleted_at.is_(None)
                )
            )
        ).scalars().all()

        for item in found:
            key = f"{item.kind.value}:{item.subject}:{item.key_extra}:{slot}"
            # 이미 알린 사건이면 조용히 넘어간다 (같은 창을 두 번 훑으므로)
            exists = await db.scalar(select(Anomaly.id).where(Anomaly.window_key == key))
            if exists:
                continue
            db.add(
                Anomaly(
                    kind=item.kind,
                    employee_id=item.employee_id,
                    subject=item.subject,
                    detail=item.detail,
                    count=item.count,
                    ip=item.ip,
                    user_agent=item.user_agent,
                    window_key=key,
                )
            )
            for master_id in masters:
                await _notify_master(db, master_id, item)
        try:
            await db.commit()
        except IntegrityError:
            # 다른 워커가 같은 창을 먼저 넣었다 — 알림은 그쪽이 보냈다
            await db.rollback()
            return
    logger.info("이상행동 %d건 감지", len(found))


# 알림 문구 — 종류마다 첫 줄이 다르다
_TITLES = {
    AnomalyKind.BRUTE_FORCE: "로그인 반복 실패",
    AnomalyKind.FORBIDDEN_BURST: "권한 없는 요청 반복",
    AnomalyKind.NEW_DEVICE: "새로운 곳에서 로그인",
    AnomalyKind.BULK_DELETE: "짧은 시간에 대량 삭제",
    AnomalyKind.READ_BURST: "대화 열람 급증",
}


async def _notify_master(db: AsyncSession, master_id: str, item: Found) -> None:
    # 순환 import 를 피하려고 여기서 부른다 (notifications → models → workers)
    from app.services.notifications import notify

    await notify(
        db,
        employee_id=master_id,
        type="ANOMALY",
        title=_TITLES.get(item.kind, "이상 징후"),
        body=f"{item.subject} · {item.detail}",
        link="/monitoring",
    )
