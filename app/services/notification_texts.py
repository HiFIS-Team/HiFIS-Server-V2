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


def leave_decision(approved: bool, start_date, end_date, reason: str | None = None) -> dict:
    verb = "승인" if approved else "반려"
    body = f"{start_date} ~ {end_date}"
    if not approved and reason:
        body += f" · 사유: {reason}"
    return {"type": "LEAVE", "title": f"휴가 신청이 {verb}되었습니다", "body": body, "link": "/attendance"}


# ── 공지 ──
def new_notice(title: str, body: str | None) -> dict:
    return {
        "type": "NOTICE",
        "title": f"새 공지 · {title}",
        "body": (body or "")[:120],
        "link": "/notices",
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
def project_request(label: str, project_title: str, requester_name: str) -> dict:
    # label = "기한 연장" | "누락 사유"
    return {
        "type": "PROJECT",
        "title": f"프로젝트 {label} 요청",
        "body": f"{project_title} · {requester_name}",
        "link": "/projects",
    }


def project_request_decided(label: str, approved: bool, project_title: str, reject_reason: str | None = None) -> dict:
    if approved:
        return {"type": "PROJECT", "title": f"프로젝트 {label} 승인", "body": f"{project_title} · 새 마감 반영", "link": "/projects"}
    return {"type": "PROJECT", "title": f"프로젝트 {label} 반려", "body": f"{project_title} · 사유: {reject_reason}", "link": "/projects"}


# ── 프로젝트 마감 리마인더(스케줄러) ──
def project_due_soon(days: int, project_title: str) -> dict:
    return {"type": "PROJECT", "title": f"프로젝트 마감 D-{days}", "body": project_title, "link": "/projects"}


def project_due_today(project_title: str) -> dict:
    return {"type": "PROJECT", "title": "오늘 프로젝트 마감!", "body": project_title, "link": "/projects"}


def project_overdue(project_title: str) -> dict:
    return {"type": "PROJECT", "title": "프로젝트가 누락됐어요", "body": project_title, "link": "/projects"}


# ── 급여 ──
def payslip_approved(year_month: str) -> dict:
    return {"type": "PAYROLL", "title": "급여 신청이 승인되었어요", "body": f"{year_month} 급여명세서가 승인됐어요. 지급이 확정됩니다.", "link": "/payroll"}


def payslip_rejected(reason: str | None) -> dict:
    return {"type": "PAYROLL", "title": "급여 신청이 반려되었어요", "body": reason, "link": "/payroll"}


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
