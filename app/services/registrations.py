"""등록권을 만들 때의 공통 판단 — **기존 회원**을 뒤늦게 넣는 경우가 여기 있다.

앱을 켜기 한참 전에 등록했거나 이미 세션이 끝난 회원을 나중에 넣을 수 있어야
한다 (2026-08-21 요청). 그런데 그 지난 실적이 **오늘 실적으로 잡히면 안 된다.**

가르는 값은 딱 하나, **결제일(`purchased_at`)** 이다. `기존` 이라는 등록 종류를
따로 만들지 않는다 — 만들면 매출·점수·급여·통계가 전부 그 값을 따로 봐야 하고,
어디 한 곳이라도 빠뜨리면 그 자리만 조용히 틀린다.

| | 어떻게 되나 |
|---|---|
| 매출 랭킹 | `purchased_at` 으로 거른다 → 지난 달 결제는 이번 달에 안 잡힌다 |
| 방문 경로 점수 | 지난 달 결제면 **안 준다** ([counts_now]) |
| 급여 커미션 | **원래 영향이 없다** — 등록이 아니라 수행한 세션 싸인마다 붙는다 |

두 라우트(`POST /members` 의 첫 등록권, `POST /registrations` 의 재등록)가
같이 쓴다. 한쪽만 고치면 같은 값이 경로에 따라 다르게 처리된다.
"""

import logging
import re
from datetime import datetime, timezone

from fastapi import HTTPException

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import RegistrationType, RenewIntent
from app.models.members.pt_survey import PtSurvey
from app.models.members.member import Member
from app.models.members.registration import Registration
from app.models.staff.employee import Employee
from app.services import notification_texts as ntext
from app.services.notifications import boss_ids, notify

from app.core.periods import KST
from app.enums import RegistrationStatus, ScoreCategory
from app.services.scoring import accrue_score

#: 매출성과 점수 — 결제액 10,000원이 기본 1점, 거기에 배율을 곱한다.
#: 55만원 결제 → 55 × 0.25 = 13.75 → **14점**
SALES_WON_PER_POINT = 10_000
SALES_MULTIPLIER = 0.25



logger = logging.getLogger(__name__)

def sales_points(price_paid: int) -> int:
    return round(price_paid / SALES_WON_PER_POINT * SALES_MULTIPLIER)


async def accrue_sales_score(
    db: AsyncSession, registration: Registration, trainer: Employee
) -> None:
    """등록권 하나가 만들어질 때 **바로** 매출성과 점수를 쌓는다 (2026-08-31 대표 요청).

    예전에는 급여 마감이 그 달 매출을 통째로 더해 한 번에 매겼다. 그러면
    **한 달이 끝나야 점수가 보이고**, 급여 개시일 전 주기는 마감이 통째로
    건너뛰어서 그 달 매출이 점수로 영영 안 남았다 (8월 6,626만원이 그랬다).
    등록하는 순간 매기면 두 문제가 같이 없어진다.

    **지난 달 결제는 안 준다** — 기존 회원을 뒤늦게 넣는 자리가 있어서다
    ([counts_now] 와 같은 기준, 방문 경로 점수도 같은 규칙이다).

    `source_ref_id` 가 등록권 id 라 **한 등록권에 한 번만** 쌓인다. 랭킹의
    매출 탭은 `sales:%` 로 거르므로 그대로 걸린다.
    """
    if not counts_now(registration.purchased_at):
        return
    points = sales_points(registration.price_paid)
    if points <= 0:
        return
    await accrue_score(
        db,
        employee_id=trainer.id,
        branch_id=trainer.branch_id,
        category=ScoreCategory.CONTRIB,
        points=points,
        source_ref_id=f"sales:{registration.id}",
        period=registration.purchased_at.astimezone(KST).strftime("%Y-%m"),
        reason="매출성과(자동)",
    )




def counts_now(purchased_at: datetime | None, *, now: datetime | None = None) -> bool:
    """이번 달 실적으로 칠 결제인가.

    **달 단위로 가른다** — 매출 랭킹·점수가 달로 집계되기 때문이다. 같은 달
    안에서 며칠 늦게 입력한 것은 이번 달 실적이 맞으므로 그대로 친다.

    안 주면(`None`) 지금 결제한 것이라 참이다 — 옛 앱이 이 값을 안 보낸다.
    """
    if purchased_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    return purchased_at.astimezone(KST).strftime("%Y-%m") >= now.astimezone(KST).strftime("%Y-%m")


def initial_status(used_sessions: int, total_sessions: int) -> RegistrationStatus:
    """만들 때의 상태 — **이미 다 쓴 등록권은 처음부터 만료다.**

    이력으로만 넣는 기존 회원(세션이 이미 끝난 사람)이 여기 든다. `ACTIVE` 로
    두면 남은 회차가 0인데 유효한 등록권으로 보여서, 세션 싸인 화면에 뜨고
    누르면 그제서야 막힌다.
    """
    if used_sessions >= total_sessions:
        return RegistrationStatus.EXPIRED
    return RegistrationStatus.ACTIVE


def ensure_used_within(used_sessions: int, total_sessions: int) -> None:
    """이미 쓴 회차가 총 회차를 넘으면 막는다.

    넘으면 남은 회차가 음수가 되어 화면이 `-3회 남음` 으로 뜬다.
    """
    if used_sessions > total_sessions:
        raise HTTPException(
            400,
            detail={
                "code": "USED_OVER_TOTAL",
                "message": "이미 받은 회차가 총 회차보다 많습니다",
            },
        )


async def notify_registered(
    db: AsyncSession, registration: Registration, trainer: Employee
) -> None:
    """회원이 등록했다고 알린다 — **대표·관리자와 그 트레이너 본인**에게.

    세션 싸인 알림과 같은 명단이다. 본인을 빼면 자기가 받은 등록을 자기만 모른다.

    **신규와 재등록을 말로 가른다** — 재등록은 그 트레이너가 붙잡은 것이라
    뜻이 다르다 (`ntext.member_registered`).

    **실패해도 등록은 그대로 둔다.** 알림은 곁가지라 여기서 막으면 등록이
    안 남는다 — 세션 싸인과 같은 규칙이다.
    """
    member = await db.get(Member, registration.member_id)
    text = ntext.member_registered(
        trainer.name,
        member.name if member else "",
        registration.type is RegistrationType.NEW,
        registration.total_sessions,
    )
    try:
        for eid in dict.fromkeys([*await boss_ids(db), trainer.id]):
            await notify(db, employee_id=eid, **text)
        await db.commit()
    except Exception:
        logger.warning("[member-register] 알림 실패 — 등록은 그대로 둔다", exc_info=True)


async def close_unanswered_surveys(db: AsyncSession, registration: Registration) -> int:
    """재등록하면 **답을 안 낸 PT 만족도 설문을 '연장됐어요' 로 닫는다** (2026-09-28).

    물어보려던 것(연장할까요)이 이미 결제로 정해졌다. 미응답에 그대로 두면
    챙길 사람 목록에 계속 남고, 예상 매출에는 안 잡힌다. 닫은 설문은 답변
    쪽으로 옮겨 가고 **재등록 금액이 그달 매출로 잡힌다** (`renewal_id`).
    다음 설문은 평소대로 누적 7회차마다 다시 나간다.

    **같은 회원이면 이름·연락처로도 찾는다.** 재등록을 새 회원으로 다시
    넣는 일이 있어서, 회원 id 만 보면 옛 회원의 미응답이 안 닫힌다.

    커밋은 부르는 쪽이 한다 — 등록과 한 번에 들어가야 한다.
    """
    if registration.type is not RegistrationType.RENEWAL:
        return 0
    member = await db.get(Member, registration.member_id)
    if member is None:
        return 0
    same = PtSurvey.member_id == member.id
    digits = re.sub(r"\D", "", member.phone or "")
    if digits:
        same = or_(
            same,
            and_(
                func.trim(Member.name) == member.name.strip(),
                func.regexp_replace(Member.phone, r"\D", "", "g") == digits,
            ),
        )
    surveys = (
        await db.scalars(
            select(PtSurvey)
            .join(Member, Member.id == PtSurvey.member_id)
            .where(PtSurvey.answered_at.is_(None), same)
        )
    ).all()
    now = datetime.now(timezone.utc)
    for survey in surveys:
        survey.renew = RenewIntent.RENEWED
        survey.renewal_id = registration.id
        survey.answered_at = now
    return len(surveys)
