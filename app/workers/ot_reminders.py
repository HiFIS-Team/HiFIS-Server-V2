"""OT 재촉 — **매시간** (2026-09-28 대표 요청). 빨리 배정하고 빨리 확정하라는 것이다.

| 무엇이 남았나 | 누구에게 |
|---|---|
| 미배정 | MASTER·ADMIN + 그 지점 전원 |
| 배정됐는데 수락 전 | 배정받은 사람 |

KST 09~23 매시 정각. **알림함에 안 남긴다 — 푸시만** (하루 열 몇 번이라
남기면 알림함이 도배된다 — 동료평가 재촉과 같은 규칙). 놓친 것은 홈 카드가 받는다.
"""

import logging
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.periods import KST
from app.db.session import SessionLocal
from app.enums import OtStatus
from app.models.members.ot_request import OtRequest
from app.models.staff.branch import Branch
from app.services import notification_texts as ntext
from app.services import sms
from app.services.notifications import boss_ids, branch_ids, send_push
from app.services.ot_requests import when_label

logger = logging.getLogger(__name__)

#: 재촉하는 시간 — 밤에는 안 울린다 (동료평가 재촉과 같은 창)
REMIND_FROM_HOUR = 9
REMIND_TO_HOUR = 23


async def ot_reminders(now: datetime | None = None) -> None:
    """[now] 는 테스트에서 시계를 옮기려고 받는다."""
    now_kst = (now or datetime.now(timezone.utc)).astimezone(KST)
    if not REMIND_FROM_HOUR <= now_kst.hour <= REMIND_TO_HOUR:
        return
    async with SessionLocal() as db:
        rows = list(
            await db.scalars(
                select(OtRequest).where(
                    OtRequest.status.in_([OtStatus.PENDING, OtStatus.ASSIGNED])
                )
            )
        )
        pending = Counter(r.branch_id for r in rows if r.status == OtStatus.PENDING)
        sent = 0

        # 미배정 — 대표·관리자는 전 지점을 한 번에, 지점 사람은 자기 지점 것만
        if pending:
            total = sum(pending.values())
            for eid in await boss_ids(db):
                await send_push(db, employee_id=eid, **ntext.ot_unassigned(total, None))
                sent += 1
            for branch_id, count in pending.items():
                branch = await db.get(Branch, branch_id)
                label = sms.branch_label(branch.name) if branch else None
                for eid in await branch_ids(db, branch_id):
                    await send_push(db, employee_id=eid, **ntext.ot_unassigned(count, label))
                    sent += 1

        # 수락 대기 — 맡은 사람에게
        for r in rows:
            if r.status == OtStatus.ASSIGNED and r.assignee_id:
                await send_push(
                    db, employee_id=r.assignee_id, **ntext.ot_accept_nudge(r.name, when_label(r))
                )
                sent += 1
        await db.commit()
        if sent:
            logger.info("ot_reminders: %d건", sent)
