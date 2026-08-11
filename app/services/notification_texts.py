"""알림 문구(멘트) 중앙 모듈 — 모든 title/body/type/link 를 여기 한 곳에서 관리.

각 함수는 notify()/send_push() 에 `**` 로 펼칠 dict 를 돌려준다:
    await notify(db, employee_id=eid, **attendance_scan("출근", when))
문구를 바꾸려면 **이 파일만** 고치면 된다(프론트 영향 없음 — 순수 문자열).
link 는 앱 내 딥링크. type 은 NotificationOut.type(프론트 분기용).
"""

from datetime import datetime


# ── 근태 · 휴가 ──
def attendance_scan(action: str, when: datetime) -> dict:
    # action = "출근" | "퇴근", when = KST datetime
    return {
        "type": "ATTENDANCE",
        "title": f"{action} 완료",
        "body": f"{when:%H:%M} {action} 처리됐어요",
        "link": "/attendance",
    }


def offhours_award(kind: str, points: int) -> dict:
    # kind = "조기 출근" | "초과 근무" — 스캔이 기본 근무시간보다 30분+ 이르거나 늦을 때 자동 적립
    return {
        "type": "ATTENDANCE",
        "title": f"근무 외 출근 +{points}점",
        "body": f"{kind}으로 근무 외 출근 점수 {points}점이 자동 적립됐어요",
        "link": "/ranking",
    }


def leave_decision(approved: bool, start_date, end_date, reason: str | None = None) -> dict:
    verb = "승인" if approved else "반려"
    body = f"{start_date} ~ {end_date}"
    if not approved and reason:
        body += f" · 사유: {reason}"
    return {"type": "LEAVE", "title": f"휴가 신청이 {verb}되었습니다", "body": body, "link": "/attendance"}


# ── 공지 ──
def new_notice(title: str, body: str | None, notice_id: str) -> dict:
    return {
        "type": "NOTICE",
        "title": f"새 공지 · {title}",
        "body": (body or "")[:120],
        "link": f"/notices/{notice_id}",  # 목록이 아니라 해당 공지로 딥링크
    }


# ── 사내톡 ──
def chat_message(*, room_id: str, sender_name: str, is_group: bool, room_name: str | None, body: str) -> dict:
    preview = body.strip() if body.strip() else "(사진)"
    if is_group and room_name:
        title, text = room_name, f"{sender_name}: {preview}"
    else:
        title, text = sender_name, preview
    return {"type": "CHAT", "title": title, "body": text, "link": f"/chat/rooms/{room_id}"}


# ── 전자결재 ──
def _approval(title: str, approval_title: str, approval_id: str) -> dict:
    return {"type": "APPROVAL", "title": title, "body": approval_title, "link": f"/approvals/{approval_id}"}


def approval_requested(approval_title: str, approval_id: str) -> dict:
    return _approval("결재 요청이 도착했습니다", approval_title, approval_id)


def approval_rejected(approval_title: str, approval_id: str) -> dict:
    return _approval("결재가 반려되었습니다", approval_title, approval_id)


def approval_approved(approval_title: str, approval_id: str) -> dict:
    return _approval("결재가 최종 승인되었습니다", approval_title, approval_id)


def approval_withdrawn(approval_title: str, approval_id: str) -> dict:
    return _approval("결재 요청이 회수되었습니다", approval_title, approval_id)


# ── 프로젝트 요청(연장/누락사유) ──
#
# **링크에 프로젝트 id 를 싣는다** (`/projects/{id}`). 목록 주소만 주면 앱이
# 탭까지만 옮기고 어느 프로젝트인지 몰라서, 받은 사람이 목록에서 다시 찾아야 한다.
# 공지도 같은 이유로 id 를 싣게 고쳤다 (backend-gap 35번).
def _project_link(project_id: str | None) -> str:
    return f"/projects/{project_id}" if project_id else "/projects"


def project_request(
    label: str, project_title: str, requester_name: str, project_id: str | None = None
) -> dict:
    # label = "기한 연장" | "누락 사유"
    return {
        "type": "PROJECT",
        "title": f"프로젝트 {label} 요청",
        "body": f"{project_title} · {requester_name}",
        "link": _project_link(project_id),
    }


def project_request_decided(
    label: str,
    approved: bool,
    project_title: str,
    reject_reason: str | None = None,
    project_id: str | None = None,
) -> dict:
    link = _project_link(project_id)
    if approved:
        return {"type": "PROJECT", "title": f"프로젝트 {label} 승인", "body": f"{project_title} · 새 마감 반영", "link": link}
    return {"type": "PROJECT", "title": f"프로젝트 {label} 반려", "body": f"{project_title} · 사유: {reject_reason}", "link": link}


# ── 프로젝트 마감 리마인더(스케줄러) ──
def project_due_soon(days: int, project_title: str, project_id: str | None = None) -> dict:
    return {"type": "PROJECT", "title": f"프로젝트 마감 D-{days}", "body": project_title, "link": _project_link(project_id)}


def project_due_today(project_title: str, project_id: str | None = None) -> dict:
    return {"type": "PROJECT", "title": "오늘 프로젝트 마감!", "body": project_title, "link": _project_link(project_id)}


def project_overdue(project_title: str, project_id: str | None = None) -> dict:
    return {"type": "PROJECT", "title": "프로젝트가 누락됐어요", "body": project_title, "link": _project_link(project_id)}


# ── 급여 ──
def payslip_approved(year_month: str) -> dict:
    return {"type": "PAYROLL", "title": "급여 신청이 승인되었어요", "body": f"{year_month} 급여명세서가 승인됐어요. 지급이 확정됩니다.", "link": "/payroll"}


def payslip_rejected(reason: str | None) -> dict:
    return {"type": "PAYROLL", "title": "급여 신청이 반려되었어요", "body": reason, "link": "/payroll"}


def payslip_paid(year_month: str) -> dict:
    return {"type": "PAYROLL", "title": "급여가 지급되었어요", "body": f"{year_month} 급여가 지급 완료됐어요.", "link": "/payroll"}


def payday_today(year_month: str) -> dict:
    return {"type": "PAYROLL", "title": "오늘 급여를 신청하세요", "body": f"{year_month} 급여 지급일이에요. 명세서를 확인하고 신청해주세요.", "link": "/payroll"}


def payday_tomorrow(year_month: str) -> dict:
    return {"type": "PAYROLL", "title": "내일 급여 신청일이에요", "body": f"{year_month} 급여 지급일은 내일이에요. 미리 확인해두세요.", "link": "/payroll"}


def payday_deadline(year_month: str) -> dict:
    return {"type": "PAYROLL", "title": "급여 신청 마감 임박 (오늘 20시)", "body": f"{year_month} 급여를 아직 신청하지 않았어요. 오늘 안에 신청해주세요.", "link": "/payroll"}


# ── 일정 ──
def event_reminder(label: str, event_title: str, start_at: datetime) -> dict:
    # label = "오늘" | "D-7"…, start_at = KST datetime
    return {"type": "SCHEDULE", "title": f"일정 {label} · {event_title}", "body": f"{start_at:%m/%d %H:%M} 시작", "link": "/schedule"}


# ── 랭킹 ──
def ranking_winner(period: str, label: str) -> dict:
    # label = "종합왕"|"매출왕"…
    return {"type": "RANKING", "title": f"🏆 {period} {label} 1위!", "body": f"지난달 {label}에 뽑혔어요. 축하합니다!", "link": "/ranking"}


def ranking_announce(period: str, summary: str) -> dict:
    return {"type": "RANKING", "title": f"📢 {period} 랭킹 발표", "body": summary, "link": "/ranking"}


def ranking_drop(label: str, overtaker_text: str, old_rank: int, new_rank: int) -> dict:
    return {"type": "RANKING", "title": f"{label} 순위 하락", "body": f"{overtaker_text} 님이 당신을 앞질렀어요 ({old_rank}위 → {new_rank}위)", "link": "/ranking"}


def ranking_change_admin(label: str, summary: str) -> dict:
    return {"type": "RANKING", "title": f"{label} 순위 변동", "body": summary, "link": "/ranking"}


# ── 대표·관리자에게 가는 전사 알림 ──
#
# 위의 것들은 **본인 일**을 본인에게 알린다. 아래는 **남의 일**을 대표·관리자에게
# 알리는 것이라 성격이 다르다. 받는 사람은 `notifications.boss_ids()` 가 정한다.
#
# 출퇴근은 사람 수 × 2 라 하루 수십 번 울린다 (2026-08-11 대표 결정 — 찍을 때마다
# 한 건씩). 줄여야 할 일이 생기면 문구가 아니라 **부르는 쪽**을 손봐야 한다.
def staff_attendance(name: str, action: str, when: datetime, note: str | None = None) -> dict:
    # action = "출근" | "퇴근", note = "지각" 처럼 **정상이 아닐 때만**
    body = f"{when:%H:%M}"
    if note:
        body += f" · {note}"
    return {"type": "ATTENDANCE", "title": f"{name} {action}", "body": body, "link": "/attendance"}


def staff_absent(name: str) -> dict:
    return {
        "type": "ATTENDANCE",
        "title": f"{name} 결근",
        "body": "퇴근 시간이 지나도록 출근 기록이 없어요",
        "link": "/attendance",
    }


#: 휴가 종류 → 사람이 읽는 말
_LEAVE_LABELS = {"ANNUAL": "연차", "HALF": "반차", "SICK": "병가", "FIELD": "외근", "ETC": "기타"}


def leave_label(leave_type, half_period=None) -> str:
    if str(leave_type) == "HALF" and half_period:
        return f"{'오전' if str(half_period) == 'AM' else '오후'} 반차"
    return _LEAVE_LABELS.get(str(leave_type), "휴가")


def leave_requested(name: str, kind: str, start_date, end_date) -> dict:
    period = f"{start_date}" if start_date == end_date else f"{start_date} ~ {end_date}"
    return {
        "type": "LEAVE",
        "title": "휴가 신청이 올라왔어요",
        "body": f"{name} · {kind} · {period}",
        "link": "/attendance",
    }


def project_created(project_title: str, author_name: str, project_id: str | None = None) -> dict:
    return {
        "type": "PROJECT",
        "title": "새 프로젝트가 만들어졌어요",
        "body": f"{project_title} · {author_name}",
        "link": _project_link(project_id),
    }


def project_completed(project_title: str, project_id: str | None = None) -> dict:
    return {
        "type": "PROJECT",
        "title": "프로젝트가 완료됐어요",
        "body": project_title,
        "link": _project_link(project_id),
    }


def project_overdue_admin(project_title: str, who: str, project_id: str | None = None) -> dict:
    return {
        "type": "PROJECT",
        "title": "프로젝트가 누락됐어요",
        "body": f"{project_title} · {who}",
        "link": _project_link(project_id),
    }


def meeting_created(meeting_title: str, author_name: str, meeting_id: str) -> dict:
    return {
        "type": "MEETING",
        "title": "새 회의록이 올라왔어요",
        "body": f"{meeting_title} · {author_name}",
        "link": f"/meetings/{meeting_id}",
    }


#: 직급 → 사람이 읽는 말 (앱 `Rank.label` 과 같은 말을 쓴다)
_RANK_LABELS = {
    "TRAINER": "트레이너",
    "FC": "FC",
    "MARKETER": "마케터",
    "TEAM_LEAD": "팀장",
    "STORE_MANAGER": "점장",
    "DEVELOPER": "개발자",
    "CEO": "대표",
}


def rank_label(rank) -> str | None:
    return _RANK_LABELS.get(str(rank))


def employee_joined(name: str, branch_name: str | None, rank_label: str | None) -> dict:
    detail = " · ".join(x for x in (branch_name, rank_label) if x)
    return {
        "type": "STAFF",
        "title": "새 직원이 가입했어요",
        "body": f"{name}{f' · {detail}' if detail else ''}",
        "link": "/staff",
    }


def employee_resigned(name: str) -> dict:
    return {"type": "STAFF", "title": "퇴사 처리됐어요", "body": name, "link": "/staff"}
