"""회원 친절도 — 외부 웹훅 수신 + 조회 (CLAUDE.md §4.5).

POST /webhooks/kindness-survey: 앱 UI 작성 없음, 외부 폼 전용. 시크릿 검증 후 KINDNESS +10.
"""

import asyncio
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import branch_filter, get_current_user, require_role
from app.core.ratelimit import limiter
from app.db.session import get_db
from app.enums import ComplaintStatus, Role, ScoreCategory
from app.models.staff.employee import Employee
from app.models.scoring.env import EnvItem, EnvTaskLog
from app.models.scoring.kindness import KindnessSurvey
from app.models.staff.branch import Branch
from app.schemas.scoring.kindness import (
    ComplaintStatusUpdate,
    KindnessSurveyOut,
    KindnessSurveyWebhook,
)
from app.services import notification_texts as ntext
from app.services.notifications import boss_ids, branch_ids, master_ids, notify
from app.services import sms
from app.services.scoring import accrue_score
from app.services.summarize import summarize_complaint

logger = logging.getLogger(__name__)

KINDNESS_POINTS = 10

router = APIRouter(tags=["kindness"])


async def _verify_webhook_secret(x_webhook_secret: str | None = Header(None)) -> None:
    if x_webhook_secret is None or not hmac.compare_digest(
        x_webhook_secret, settings.kindness_webhook_secret
    ):
        raise HTTPException(401, detail={"code": "INVALID_WEBHOOK_SECRET", "message": "웹훅 시크릿이 올바르지 않습니다"})


@router.post(
    "/webhooks/kindness-survey",
    response_model=KindnessSurveyOut,
    status_code=201,
    dependencies=[Depends(_verify_webhook_secret)],
)
@limiter.limit("30/minute")  # IP당 분 30회 — 웹훅 스팸/포인트 남용 방지(§M4)
async def receive_kindness_survey(
    request: Request, payload: KindnessSurveyWebhook, db: AsyncSession = Depends(get_db)
) -> KindnessSurvey:
    if not payload.consent:
        raise HTTPException(400, detail={"code": "CONSENT_REQUIRED", "message": "개인정보 동의가 필요합니다"})
    employee = await db.get(Employee, payload.praised_employee_id)
    if employee is None:
        raise HTTPException(400, detail={"code": "EMPLOYEE_NOT_FOUND", "message": "칭찬 대상 직원이 존재하지 않습니다"})

    survey = KindnessSurvey(
        motivation=payload.motivation,
        praised_employee_id=payload.praised_employee_id,
        praise_comment=payload.praise_comment,
        improvement=payload.improvement,
        member_name=payload.member_name,
        member_phone=payload.member_phone,
        consent=True,
    )
    db.add(survey)
    await db.flush()
    await accrue_score(
        db,
        employee_id=payload.praised_employee_id,
        branch_id=employee.branch_id,
        category=ScoreCategory.KINDNESS,
        points=KINDNESS_POINTS,
        source_ref_id=survey.id,
        reason="회원 친절도 칭찬",
    )
    await _notify_survey(db, survey, employee)
    await db.commit()
    await db.refresh(survey)
    return survey


async def _branch_name(db: AsyncSession, branch_id: str | None) -> str | None:
    if branch_id is None:
        return None
    branch = await db.get(Branch, branch_id)
    return branch.name if branch else None


async def _notify_survey(
    db: AsyncSession, survey: KindnessSurvey, praised: Employee
) -> None:
    """설문이 들어왔다고 알린다 (2026-08-31 대표 요청).

    | | 칭찬 | 컴플레인 |
    |---|---|---|
    | 칭찬받은 본인 | ✅ | — |
    | MASTER · ADMIN | ✅ | ✅ **전 지점** |
    | 그 지점 MANAGER · MEMBER | — | ✅ **자기 지점만** |

    **칭찬은 지점에 안 뿌린다.** 남이 칭찬받은 것은 그 사람과 대표가 알면
    되는 일이고, 지점 전원에게 가면 하루에도 여러 번 울린다.
    반대로 컴플레인은 **매장 전체가 고치는 일**이라 지점이 같이 받는다.
    """
    branch = await _branch_name(db, praised.branch_id)
    bosses = await boss_ids(db)

    comment = (survey.praise_comment or "").strip()
    if comment:
        await notify(
            db,
            employee_id=praised.id,
            **ntext.kindness_praise(survey.member_name, comment),
        )
        for eid in bosses:
            if eid == praised.id:
                continue
            await notify(db, employee_id=eid, **ntext.kindness_praise_boss(praised.name, comment))

    improvement = (survey.improvement or "").strip()
    if not improvement:
        return
    for eid in bosses:
        await notify(db, employee_id=eid, **ntext.kindness_complaint(improvement, branch))
    for eid in await branch_ids(db, praised.branch_id):
        await notify(db, employee_id=eid, **ntext.kindness_complaint(improvement, None))


async def _make_summary(survey: KindnessSurvey) -> None:
    """해결된 컴플레인을 **한 줄로 줄여 박아 둔다** (2026-09-08 대표 요청).

    완료가 찍히는 자리가 둘이라(대표가 직접 · 대표가 승인) **여기 하나로 모은다** —
    한쪽만 걸면 대표가 직접 처리한 건에는 요약이 안 붙는다.

    **못 만들어도 그냥 넘어간다.** 요약은 곁가지고, 없으면 TV 가 원문을 쓴다.
    여기서 막으면 바깥 API 가 죽었을 때 컴플레인을 해결 처리할 수 없게 된다.
    """
    if survey.summary:
        return  # 이미 있다 — 다시 부르면 벽에 걸린 문장이 저 혼자 바뀐다
    survey.summary = await summarize_complaint(survey.improvement or "")


#: 회원에게 가는 문자 (2026-09-08 대표 결정).
#:
#: **정보성 문자다** — 광고가 아니라 본인이 남긴 의견에 대한 응대라,
#: `(광고)` 표기도 야간 발송 제한(21~08시)도 해당이 없다. 설문 동의의
#: 이용 목적이 「설문 내용 확인 및 응대」라 동의 범위 안이기도 하다.
#:
#: **무슨 의견이 반영됐는지를 반드시 싣는다.** 몇 주 전에 적은 것이라
#: 그게 없으면 받는 사람이 무슨 문자인지 모른다. 그래서 90바이트를 넘겨
#: LMS 로 나가는데, 그건 알고 그렇게 두는 것이다.
_SMS_SUBJECT = "불편사항 개선 안내"

_SMS_TEMPLATE = """[피트니스스타 {branch}]

말씀해 주신 불편사항이 개선되었습니다.

「{opinion}」

바쁘신 중에도 시간 내어 의견 남겨 주셔서 진심으로 감사드립니다.
회원님의 한마디가 저희가 놓치고 있던 것을 알려 주었습니다.

앞으로도 불편하신 점이 있으면 언제든 편하게 말씀해 주세요.
더 나은 공간으로 보답하겠습니다."""

#: 문자에 실을 의견 길이 상한 — 넘으면 뒤를 자른다.
#:
#: 요약(`summary`)이 있으면 35자 안쪽이라 안 걸린다. 요약을 못 만들었거나
#: 짧아서 안 줄인 것이 원문으로 오는데, 그때도 문자가 무한정 길어지면 안 된다.
_SMS_OPINION_MAX = 80


async def _sms_resolved(db: AsyncSession, survey: KindnessSurvey) -> None:
    """의견을 남긴 **회원에게** 해결됐다고 문자를 보낸다 (2026-09-08 대표 요청).

    **발신번호는 그 지점 번호다** (`branches.sms_sender`). 회원이 되걸면 그
    매장에 닿아야 한다 — 번호가 안 적혀 있으면 **안 보낸다.** 기본 번호로
    대신 보내면 화순 회원이 첨단으로 전화하는 셈이 된다.

    **실패해도 그냥 넘어간다.** 문자는 곁가지고, 여기서 막으면 솔라피가
    죽었을 때 컴플레인을 해결 처리할 수 없게 된다 (요약과 같은 규칙).

    두 번 보내지 않도록 `sms_sent_at` 을 본다 — 완료가 찍히는 자리가 둘이다.
    """
    if survey.sms_sent_at:
        return
    to = (survey.member_phone or "").strip()
    if not to:
        return

    praised = await db.get(Employee, survey.praised_employee_id)
    branch = await db.get(Branch, praised.branch_id) if praised else None
    sender = (branch.sms_sender or "").strip() if branch else ""
    if not sender or not sms.ready(sender):
        logger.info(
            "[complaint-sms] 발신번호가 없어 건너뜀 branch=%s", branch.name if branch else "?"
        )
        return

    # TV 에 걸리는 것과 **같은 줄**을 보낸다 — 벽에 걸린 말과 문자가 다르면
    # 회원이 받았을 때 자기 것인지 헷갈린다
    opinion = ((survey.summary or "").strip() or (survey.improvement or "").strip())
    if len(opinion) > _SMS_OPINION_MAX:
        opinion = opinion[: _SMS_OPINION_MAX - 1].rstrip() + "…"

    text = _SMS_TEMPLATE.format(branch=sms.branch_label(branch.name), opinion=opinion)
    try:
        await asyncio.to_thread(
            sms.send_sync, to, text,
            sender=sender, subject=_SMS_SUBJECT, tag="complaint-sms",
        )
    except Exception:
        logger.warning("[complaint-sms] 발송 실패 — 해결 처리는 그대로 둔다", exc_info=True)
        return
    survey.sms_sent_at = datetime.now(timezone.utc)


async def _notify_resolved(
    db: AsyncSession, survey: KindnessSurvey, resolver: Employee
) -> None:
    """컴플레인을 **누가** 해결했는지 알린다 (2026-08-31 대표 요청).

    받는 사람은 들어올 때와 같다 — 그 지점과 MASTER·ADMIN. 들어온 것만
    알리고 끝난 것을 안 알리면 매장에 컴플레인이 계속 걸려 있는 것처럼 보인다.

    **지점은 컴플레인이 난 지점이다** (칭찬받은 직원의 지점). 처리한 사람이
    다른 지점에서 도와준 경우에도 알림은 그 매장으로 간다.
    """
    praised = await db.get(Employee, survey.praised_employee_id)
    branch_id = praised.branch_id if praised else None
    branch = await _branch_name(db, branch_id)
    improvement = (survey.improvement or "").strip()

    # **처리한 본인은 뺀다** — 올린 사람에게는 '승인됐어요' 가 이미 가고,
    # 대표가 직접 찍었으면 자기가 한 일을 자기가 통보받는 셈이 된다
    for eid in await boss_ids(db, exclude=resolver.id):
        await notify(
            db, employee_id=eid, **ntext.kindness_resolved(resolver.name, improvement, branch)
        )
    for eid in await branch_ids(db, branch_id, exclude=resolver.id):
        await notify(
            db, employee_id=eid, **ntext.kindness_resolved(resolver.name, improvement, None)
        )


@router.get("/kindness-surveys", response_model=list[KindnessSurveyOut], dependencies=[Depends(get_current_user)])
async def list_kindness_surveys(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_filter),  # ?branchId= 로 지점을 고를 수 있다
    praised_employee_id: str | None = Query(None, alias="praisedEmployeeId"),
) -> list[KindnessSurvey]:
    stmt = select(KindnessSurvey)
    if scope:
        stmt = stmt.join(Employee, Employee.id == KindnessSurvey.praised_employee_id).where(
            Employee.branch_id == scope
        )
    if praised_employee_id:
        stmt = stmt.where(KindnessSurvey.praised_employee_id == praised_employee_id)
    result = await db.execute(stmt.order_by(KindnessSurvey.submitted_at.desc()))
    return list(result.scalars().all())


@router.patch("/kindness-surveys/{survey_id}/status", response_model=KindnessSurveyOut)
async def set_complaint_status(
    survey_id: str,
    payload: ComplaintStatusUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KindnessSurvey:
    """컴플레인 처리 단계 바꾸기 — 미처리 → 해결중 → 해결 완료.

    **미처리·해결중은 누구나 바꾼다.** 컴플레인은 매장 전체의 일이라 고친
    사람이 표시하면 된다.

    **해결 완료만 대표 승인을 받는다** (2026-08-31 대표 요청). 완료를 찍으면
    찍은 사람에게 환경정비 '클레임해결' 점수가 붙어서, 아무나 찍을 수 있으면
    점수를 그냥 가져갈 수 있다.

    | 누가 눌렀나 | 결과 |
    |---|---|
    | MASTER | 바로 `DONE` — 승인할 사람이 자기다 |
    | MANAGER · MEMBER | `DONE_REQUESTED` (승인 대기) — **점수는 아직 없다** |

    승인 대기에서 해결중·미처리를 누르면 **신청을 무른다** (잘못 누른 것을
    되돌리는 길). 승인은 `POST /kindness-surveys/{id}/approve` 다.

    **해결 완료는 되돌릴 수 없다.** 완료를 찍는 순간 점수가 들어가서,
    되돌렸다 다시 찍으면 두 번 쌓인다. 매장 TV 에 '해결 완료' 로 이미
    나간 것을 물리는 것이기도 하다.

    개선 의견이 없는 설문(칭찬만 있는 것)은 컴플레인이 아니라서 막는다.
    """
    if payload.status is ComplaintStatus.DONE_REQUESTED:
        # 서버가 매기는 값이다 — 요청자가 이걸로 건너뛰면 승인 없이 대기가 된다
        raise HTTPException(
            400,
            detail={"code": "NOT_SETTABLE", "message": "완료 승인 대기는 직접 지정할 수 없습니다"},
        )
    survey = await _complaint(db, survey_id)
    if survey.improvement_status == ComplaintStatus.DONE:
        raise HTTPException(
            400,
            detail={"code": "ALREADY_RESOLVED", "message": "이미 해결 완료된 컴플레인입니다"},
        )

    if payload.status is not ComplaintStatus.DONE:
        # 해결중·미처리로 내린다 — 올려 둔 승인 신청이 있으면 같이 무른다
        survey.improvement_status = payload.status
        survey.done_requested_by_id = None
        survey.done_requested_at = None
        await db.commit()
        await db.refresh(survey)
        return survey

    now = datetime.now(timezone.utc)
    if current.role is Role.MASTER:
        survey.improvement_status = ComplaintStatus.DONE
        survey.resolved_at = now
        survey.resolved_by_id = current.id
        await _award_claim_resolved(db, current, survey)
        await _make_summary(survey)
        await _sms_resolved(db, survey)
        await _notify_resolved(db, survey, current)
        await db.commit()
        await db.refresh(survey)
        return survey

    survey.improvement_status = ComplaintStatus.DONE_REQUESTED
    survey.done_requested_by_id = current.id
    survey.done_requested_at = now
    for eid in await master_ids(db, exclude=current.id):
        await notify(
            db,
            employee_id=eid,
            type="COMPLAINT",
            title="컴플레인 해결 완료 결재",
            body=f"{current.name} · {(survey.improvement or '').strip()}",
            link="/work",
        )
    await db.commit()
    await db.refresh(survey)
    return survey


@router.post(
    "/kindness-surveys/{survey_id}/approve",
    response_model=KindnessSurveyOut,
    dependencies=[Depends(require_role(Role.MASTER))],
)
async def approve_complaint_done(
    survey_id: str,
    db: AsyncSession = Depends(get_db),
) -> KindnessSurvey:
    """컴플레인 해결 완료 승인 — **점수는 올린 사람에게 간다.**

    대표가 눌러 준다고 대표가 치운 것은 아니다. 실제로 해결한 사람이
    `done_requested_by_id` 라 그 사람 앞으로 클레임해결 기록을 남긴다.
    """
    survey = await _complaint(db, survey_id)
    requester = await _pending_requester(db, survey)
    survey.improvement_status = ComplaintStatus.DONE
    survey.resolved_at = datetime.now(timezone.utc)
    survey.resolved_by_id = requester.id
    await _award_claim_resolved(db, requester, survey)
    await _make_summary(survey)
    await _sms_resolved(db, survey)
    await notify(
        db,
        employee_id=requester.id,
        type="COMPLAINT",
        title="컴플레인 해결이 승인됐어요",
        body=(survey.improvement or "").strip(),
        link="/work",
    )
    # 매장에도 알린다 — 올린 사람만 알면 나머지는 아직 걸려 있는 줄 안다
    await _notify_resolved(db, survey, requester)
    # **신청 흔적을 안 지운다** — 지우면 대표가 직접 찍은 완료와 구분이 안 되어
    # 결재 이력의 '승인' 칸에 대표가 혼자 처리한 것까지 선다 (일정의 `decided_at`
    # 과 같은 자리다)
    await db.commit()
    await db.refresh(survey)
    return survey


@router.post(
    "/kindness-surveys/{survey_id}/reject",
    status_code=204,
    dependencies=[Depends(require_role(Role.MASTER))],
)
async def reject_complaint_done(
    survey_id: str,
    reason: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> None:
    """해결 완료 반려 — **해결중으로 되돌린다.**

    미처리로 내리면 아무도 손대지 않은 것처럼 보인다. 실제로는 누가 붙어
    있다가 아직 덜 된 것이라 해결중이 맞다.
    """
    survey = await _complaint(db, survey_id)
    requester = await _pending_requester(db, survey)
    survey.improvement_status = ComplaintStatus.WORKING
    survey.done_requested_by_id = None
    survey.done_requested_at = None
    await notify(
        db,
        employee_id=requester.id,
        type="COMPLAINT",
        title="컴플레인 해결이 반려됐어요",
        body=f"{(survey.improvement or '').strip()}{f' · {reason}' if reason else ''}",
        link="/work",
    )
    await db.commit()
    return None


@router.delete(
    "/kindness-surveys/{survey_id}/complaint",
    status_code=204,
    dependencies=[Depends(require_role(Role.MASTER))],
)
async def delete_complaint(
    survey_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """컴플레인 지우기 — **개선 의견만 지운다** (2026-08-31 대표 요청).

    설문 한 건에 칭찬과 개선 의견이 같이 들어 있다. 줄을 통째로 지우면
    그 회원이 남긴 칭찬과 이미 붙은 친절 점수까지 같이 날아간다.
    개선 의견을 비우면 앱이 컴플레인으로 세지 않아 그 줄만 사라진다.

    **되돌릴 수 없다** — 지운 글은 어디에도 안 남는다. 활동 기록에는
    누가 언제 지웠는지가 남는다.
    """
    survey = await _complaint(db, survey_id)
    survey.improvement = None
    survey.improvement_status = ComplaintStatus.PENDING
    survey.done_requested_by_id = None
    survey.done_requested_at = None
    survey.resolved_at = None
    survey.resolved_by_id = None
    await db.commit()
    return None


async def _complaint(db: AsyncSession, survey_id: str) -> KindnessSurvey:
    """설문을 꺼내되 **컴플레인인 것만** — 넷이 같은 검사를 쓴다."""
    survey = await db.get(KindnessSurvey, survey_id)
    if survey is None:
        raise HTTPException(404, detail={"code": "SURVEY_NOT_FOUND", "message": "설문을 찾을 수 없습니다"})
    if not (survey.improvement or "").strip():
        raise HTTPException(
            400, detail={"code": "NOT_A_COMPLAINT", "message": "개선 의견이 없는 설문입니다"}
        )
    return survey


async def _pending_requester(db: AsyncSession, survey: KindnessSurvey) -> Employee:
    """승인 대기 중인 신청과 올린 사람 — 아니면 400."""
    if survey.improvement_status != ComplaintStatus.DONE_REQUESTED:
        raise HTTPException(
            400, detail={"code": "NOT_PENDING", "message": "승인을 기다리는 컴플레인이 아닙니다"}
        )
    requester = (
        await db.get(Employee, survey.done_requested_by_id)
        if survey.done_requested_by_id
        else None
    )
    if requester is None:
        raise HTTPException(
            400, detail={"code": "REQUESTER_NOT_FOUND", "message": "올린 사람을 찾을 수 없습니다"}
        )
    return requester


# 컴플레인을 끝내면 이 환경정비 항목으로 점수가 붙는다.
# **지점 항목 이름과 정확히 같아야 한다** — 이름이 바뀌면 점수가 안 들어간다.
_CLAIM_ITEM_NAME = "클레임해결"


async def _award_claim_resolved(
    db: AsyncSession, actor: Employee, survey: KindnessSurvey
) -> None:
    """해결 완료를 찍은 사람에게 환경정비 '클레임해결' 수행 기록을 남긴다.

    앱에서 칩을 눌러 남기던 자리인데, 컴플레인은 여기서 끝나므로 서버가 대신 찍는다.
    같은 항목을 두 번 세지 않도록 **완료는 되돌릴 수 없게** 위에서 막아 뒀다.

    지점에 그 항목이 없으면 조용히 넘어간다 — 점수가 안 붙을 뿐이고,
    컴플레인 처리 자체가 실패하면 안 된다.
    """
    branch_id = actor.branch_id
    if branch_id is None:
        return
    item = (
        await db.execute(
            select(EnvItem).where(
                EnvItem.branch_id == branch_id, EnvItem.name == _CLAIM_ITEM_NAME
            )
        )
    ).scalar_one_or_none()
    if item is None:
        logger.warning("클레임해결 항목이 지점 %s 에 없어 점수를 못 줬습니다", branch_id)
        return

    log = EnvTaskLog(
        employee_id=actor.id,
        branch_id=branch_id,
        env_item_id=item.id,
        item_name=item.name,
        points=item.points,
        note=(survey.improvement or "")[:200],
    )
    db.add(log)
    await db.flush()
    await accrue_score(
        db,
        employee_id=actor.id,
        branch_id=branch_id,
        category=ScoreCategory.ENV,
        points=item.points,
        created_by_id=actor.id,
        source_ref_id=log.id,
        reason=item.name,
    )
