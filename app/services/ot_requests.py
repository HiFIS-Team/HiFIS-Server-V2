"""OT 신청 — 누가 무엇을 보고, 누구에게 알리고, 언제 점수를 주나 (2026-09-28).

라우터 둘(공개 신청 · 직원 화면)과 등록권 만들기가 같이 쓴다.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.periods import KST
from app.enums import EmployeeStatus, OtStatus, Rank, RegistrationType, Role, ScoreCategory
from app.models.members.member import Member
from app.models.members.ot_request import OtRequest
from app.models.members.registration import Registration
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.services import notification_texts as ntext
from app.services import sms
from app.services.notifications import boss_ids, branch_ids, notify
from app.services.scoring import accrue_score

logger = logging.getLogger(__name__)

#: OT → PT 전환 점수 — 담당자에게 매출성과로 붙는다 (2026-09-28 대표 요청).
#: 방문 경로 'OT→PT' 5점(`VISIT_PATH_SCORE`)과 **따로** 간다
OT_CONVERT_POINTS = 10

_BOSSES = (Role.MASTER, Role.ADMIN)


def visible(stmt, current: Employee):
    """볼 수 있는 OT 만 남긴다.

    | 권한 | 무엇을 |
    |---|---|
    | MASTER·ADMIN | 전 지점 |
    | MANAGER | 자기 지점 전부 |
    | MEMBER | **자기가 배정받은 것만** — FC 는 자기 지점 **미배정**도 같이 본다 |
    """
    if current.role in _BOSSES:
        return stmt
    if current.role == Role.MANAGER:
        return stmt.where(OtRequest.branch_id == current.branch_id)
    mine = OtRequest.assignee_id == current.id
    if current.rank == Rank.FC:
        mine = or_(
            mine,
            and_(
                OtRequest.branch_id == current.branch_id,
                OtRequest.status == OtStatus.PENDING,
            ),
        )
    return stmt.where(mine)


def can_assign(current: Employee, ot: OtRequest) -> bool:
    if current.role in _BOSSES:
        return True
    return current.role == Role.MANAGER and ot.branch_id == current.branch_id


def can_take(assigner: Employee, assignee: Employee, ot: OtRequest) -> bool:
    """[assignee] 에게 맡길 수 있나.

    MASTER·ADMIN 은 **본인이 안 한다** — 그 지점 MANAGER·MEMBER 중 한 명.
    MANAGER 는 **본인 포함** 그 지점 MEMBER 까지.
    """
    if assignee.branch_id != ot.branch_id or assignee.status != EmployeeStatus.ACTIVE:
        return False
    if assigner.role in _BOSSES:
        return assignee.role in (Role.MANAGER, Role.MEMBER)
    return assignee.id == assigner.id or assignee.role == Role.MEMBER


async def notify_new(db: AsyncSession, ot: OtRequest) -> None:
    """새 신청 — **그 지점 전원 + MASTER·ADMIN** (지점 상관없이)."""
    branch = await db.get(Branch, ot.branch_id)
    text = ntext.ot_requested(
        ot.name, sms.branch_label(branch.name if branch else ""), _when(ot)
    )
    for eid in {*await branch_ids(db, ot.branch_id), *await boss_ids(db)}:
        await notify(db, employee_id=eid, **text)


def _when(ot: OtRequest) -> str:
    """`10/3(금) 14:00~15:00`"""
    day = "월화수목금토일"[ot.visit_date.weekday()]
    return (
        f"{ot.visit_date.month}/{ot.visit_date.day}({day}) "
        f"{ot.start_time:%H:%M}~{ot.end_time:%H:%M}"
    )


#: 확정 문자 — 지점 번호로 나간다 (회원이 되걸면 그 매장에 닿는다)
_SMS_TEMPLATE = (
    "[피트니스스타 {branch}] {name}님, OT 예약이 확정됐어요.\n"
    "일시: {when}\n"
    "담당: {trainer}\n"
    "시간이 안 되시면 이 번호로 연락 주세요."
)


async def sms_confirmed(db: AsyncSession, ot: OtRequest, trainer: Employee) -> None:
    """신청자에게 확정 문자 — **실패해도 확정은 그대로 둔다** (문자는 곁가지다).

    지점 발신번호가 없으면 안 보낸다 — 기본 번호로 보내면 회원이 엉뚱한
    매장으로 전화한다 (컴플레인 해결 문자와 같은 규칙).
    """
    if ot.sms_sent_at:
        return
    branch = await db.get(Branch, ot.branch_id)
    sender = (branch.sms_sender or "").strip() if branch else ""
    if not sender or not sms.ready(sender):
        logger.info("[ot-sms] 발신번호가 없어 건너뜀 branch=%s", branch.name if branch else "?")
        return
    text = _SMS_TEMPLATE.format(
        branch=sms.branch_label(branch.name), name=ot.name, when=_when(ot), trainer=trainer.name
    )
    try:
        await asyncio.to_thread(
            sms.send_sync, ot.phone, text, sender=sender, subject="OT 예약 확정", tag="ot-sms"
        )
    except Exception:
        logger.warning("[ot-sms] 발송 실패 — 확정은 그대로 둔다", exc_info=True)
        return
    ot.sms_sent_at = datetime.now(timezone.utc)


async def convert_on_registration(db: AsyncSession, registration: Registration) -> int:
    """신규 등록이 들어오면 **이름·연락처가 같은 확정 OT** 를 PT 전환으로 친다.

    담당자에게 매출성과 +10 (`sales:ot:{id}` — 매출 탭에 같이 잡힌다).
    한 OT 에 한 번만 (`converted_at`). 커밋은 부르는 쪽이 한다.
    """
    if registration.type is not RegistrationType.NEW:
        return 0
    member = await db.get(Member, registration.member_id)
    digits = re.sub(r"\D", "", member.phone or "") if member else ""
    if not digits:
        return 0
    rows = (
        await db.scalars(
            select(OtRequest).where(
                OtRequest.status == OtStatus.ACCEPTED,
                OtRequest.converted_at.is_(None),
                OtRequest.phone == digits,
                func.trim(OtRequest.name) == member.name.strip(),
            )
        )
    ).all()
    now = datetime.now(timezone.utc)
    for ot in rows:
        ot.converted_at = now
        trainer = await db.get(Employee, ot.assignee_id) if ot.assignee_id else None
        if trainer is None:
            continue
        await accrue_score(
            db,
            employee_id=trainer.id,
            branch_id=trainer.branch_id,
            category=ScoreCategory.CONTRIB,
            points=OT_CONVERT_POINTS,
            source_ref_id=f"sales:ot:{ot.id}",
            period=now.astimezone(KST).strftime("%Y-%m"),
            reason="매출성과(OT→PT 전환)",
        )
    return len(rows)
