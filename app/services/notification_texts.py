"""알림 문구(멘트) 중앙 모듈 — 모든 title/body/type/link 를 여기 한 곳에서 관리.

각 함수는 notify()/send_push() 에 `**` 로 펼칠 dict 를 돌려준다:
    await notify(db, employee_id=eid, **attendance_scan("출근", when))
문구를 바꾸려면 **이 파일만** 고치면 된다(프론트 영향 없음 — 순수 문자열).
link 는 앱 내 딥링크. type 은 NotificationOut.type(프론트 분기용).
"""

from datetime import datetime


def short(text: str | None, limit: int = 40) -> str:
    """사람이 적은 글을 알림에 실을 때 **줄바꿈을 접고 잘라서** 쓴다.

    제목·사유 칸에 길이 제한이 없어서(스키마에 `max_length` 가 없다) 길게 쓰면
    알림이 그대로 늘어난다. 여러 줄이면 세로로도 길어진다.

    **알림은 "왔다"를 알리는 자리지 읽는 자리가 아니다** — 전체는 눌러서 본다.
    """
    if not text:
        return ""
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[:limit].rstrip() + "…"


# ── 근태 · 휴가 ──
def attendance_scan(action: str, when: datetime) -> dict:
    # action = "출근" | "퇴근", when = KST datetime
    return {
        "type": "ATTENDANCE",
        "title": f"{action}했어요",
        "body": f"{when:%H:%M} 에 찍혔어요",
        "link": "/attendance",
    }


def offhours_award(kind: str, points: int) -> dict:
    # kind = "조기 출근" | "초과 근무" — 스캔이 기본 근무시간보다 30분+ 이르거나 늦을 때 자동 적립
    return {
        "type": "ATTENDANCE",
        "title": f"{kind}으로 {points}점 받았어요",
        "body": "근무 외 출근 점수가 쌓였어요",
        "link": "/ranking",
    }


def late_penalty(nth: int, points: int) -> dict:
    # 지각 차감 — 모르고 지나가면 안 되니 찍는 순간 본인에게 알린다.
    # points 가 음수라 그대로 쓰면 "-10점 깎였어요" 로 부호가 두 번 붙는다.
    return {
        "type": "ATTENDANCE",
        "title": f"지각 {nth}회 · 종합 점수 {abs(points)}점 깎였어요",
        "body": "다음부터는 조금만 일찍 나와 주세요",
        "link": "/ranking",
    }


def leave_decision(approved: bool, start_date, end_date, reason: str | None = None) -> dict:
    verb = "승인" if approved else "반려"
    body = f"{start_date} ~ {end_date}"
    if not approved and reason:
        body += f" · {short(reason)}"
    return {"type": "LEAVE", "title": f"휴가가 {verb}됐어요", "body": body, "link": "/attendance"}


# ── 공지 ──
def new_notice(title: str, body: str | None, notice_id: str) -> dict:
    return {
        "type": "NOTICE",
        "title": "새 공지가 올라왔어요",
        # **본문을 안 싣는다** (2026-08-13 대표 요청). 공지는 마크다운으로 쓰는데
        # 알림에는 그대로 나가서 `## 제목` `- 항목` 이 글자로 보였다.
        # 제목만 보여주고 자세한 건 눌러서 보게 한다.
        "body": short(title),
        "link": f"/notices/{notice_id}",  # 목록이 아니라 해당 공지로 딥링크
    }


# ── 사내톡 ──
#: 미리보기 길이 — 카톡·인스타가 보여주는 만큼
CHAT_PREVIEW = 60


def chat_message(*, room_id: str, sender_name: str, is_group: bool, room_name: str | None, body: str) -> dict:
    """사내톡 알림 — **길게 쓴 메시지는 잘라서 보여준다.**

    예전에는 길이 제한이 없어서 긴 글을 보내면 알림에 그대로 다 나갔고,
    줄바꿈까지 살아 있어 세로로 한참 늘어났다 (2026-08-13 대표 지적).

    줄바꿈·연속 공백을 한 칸으로 접고 [CHAT_PREVIEW] 자에서 자른다.
    **알림은 "왔다"를 알리는 자리지 읽는 자리가 아니다** — 전체는 눌러서 본다.
    """
    preview = " ".join(body.split()) or "(사진)"
    if len(preview) > CHAT_PREVIEW:
        preview = preview[:CHAT_PREVIEW].rstrip() + "…"
    if is_group and room_name:
        title, text = room_name, f"{sender_name}: {preview}"
    else:
        title, text = sender_name, preview
    return {"type": "CHAT", "title": title, "body": text, "link": f"/chat/rooms/{room_id}"}


# ── 전자결재 ──
def _approval(title: str, approval_title: str, approval_id: str) -> dict:
    return {"type": "APPROVAL", "title": title, "body": short(approval_title), "link": f"/approvals/{approval_id}"}


def approval_requested(approval_title: str, approval_id: str) -> dict:
    return _approval("결재할 게 있어요", approval_title, approval_id)


def approval_rejected(approval_title: str, approval_id: str) -> dict:
    return _approval("결재가 반려됐어요", approval_title, approval_id)


def approval_approved(approval_title: str, approval_id: str) -> dict:
    return _approval("결재가 승인됐어요", approval_title, approval_id)


def approval_withdrawn(approval_title: str, approval_id: str) -> dict:
    return _approval("결재가 회수됐어요", approval_title, approval_id)


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
        "title": f"{label} 신청이 왔어요",
        "body": f"{short(project_title, 30)} · {requester_name}",
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
        return {"type": "PROJECT", "title": f"{label}이 승인됐어요", "body": f"{short(project_title, 30)} · 새 마감이 반영됐어요", "link": link}
    return {"type": "PROJECT", "title": f"{label}이 반려됐어요", "body": f"{short(project_title, 30)} · {short(reject_reason)}", "link": link}


# ── 프로젝트 인원 추가 (2026-08-19) ──
#
# **`project_request_decided` 를 안 쓴다.** 그쪽 승인 본문이
# `새 마감이 반영됐어요` 로 굳어 있어서 인원 추가에는 안 맞는다.
# 거기를 고치면 기한 연장·수정·삭제 문구까지 같이 바뀐다.
def project_members_decided(
    approved: bool,
    project_title: str,
    who: str,
    reject_reason: str | None = None,
    project_id: str | None = None,
) -> dict:
    link = _project_link(project_id)
    if approved:
        return {"type": "PROJECT", "title": "인원 추가가 승인됐어요", "body": f"{short(project_title, 30)} · {who}", "link": link}
    return {"type": "PROJECT", "title": "인원 추가가 반려됐어요", "body": f"{short(project_title, 30)} · {short(reject_reason)}", "link": link}


def project_member_added(project_title: str, project_id: str | None = None) -> dict:
    return {"type": "PROJECT", "title": "프로젝트에 참여하게 됐어요", "body": short(project_title), "link": _project_link(project_id)}


# ── 프로젝트 마감 리마인더(스케줄러) ──
def project_due_soon(days: int, project_title: str, project_id: str | None = None) -> dict:
    return {"type": "PROJECT", "title": f"마감이 {days}일 남았어요", "body": short(project_title), "link": _project_link(project_id)}


def project_due_today(project_title: str, project_id: str | None = None) -> dict:
    return {"type": "PROJECT", "title": "오늘이 마감이에요", "body": short(project_title), "link": _project_link(project_id)}


def project_overdue(project_title: str, project_id: str | None = None) -> dict:
    return {"type": "PROJECT", "title": "프로젝트가 누락됐어요", "body": short(project_title), "link": _project_link(project_id)}


# ── 급여 ──
def payslip_approved(year_month: str) -> dict:
    return {"type": "PAYROLL", "title": "급여 신청이 승인됐어요", "body": f"{year_month} 지급이 확정됐어요", "link": "/payroll"}


def payslip_rejected(reason: str | None) -> dict:
    return {"type": "PAYROLL", "title": "급여 신청이 반려됐어요", "body": short(reason), "link": "/payroll"}


def payslip_paid(year_month: str) -> dict:
    return {"type": "PAYROLL", "title": "급여가 들어왔어요", "body": f"{year_month} 급여가 지급됐어요", "link": "/payroll"}


def payday_today(year_month: str) -> dict:
    return {"type": "PAYROLL", "title": "오늘 급여를 신청해 주세요", "body": f"{year_month} 급여 지급일이에요", "link": "/payroll"}


def payday_tomorrow(year_month: str) -> dict:
    return {"type": "PAYROLL", "title": "내일이 급여 신청일이에요", "body": f"{year_month} 급여를 미리 확인해 두세요", "link": "/payroll"}


def payday_deadline(year_month: str) -> dict:
    return {"type": "PAYROLL", "title": "오늘 20시까지 신청해 주세요", "body": f"{year_month} 급여를 아직 안 냈어요", "link": "/payroll"}


# ── 일정 ──
def event_reminder(days: int, event_title: str, start_at: datetime) -> dict:
    """일정 리마인더 — [days] 는 남은 날 (0 이면 오늘).

    예전에는 `D-7` 을 그대로 제목에 박았는데 알림에서 딱딱하게 읽혔다
    (2026-08-13 대표 요청). 남은 날을 말로 푼다.
    """
    when = "오늘" if days == 0 else "내일" if days == 1 else f"{days}일 뒤"
    return {
        "type": "SCHEDULE",
        "title": f"{when} 일정이 있어요",
        "body": f"{short(event_title, 30)} · {start_at:%m/%d %H:%M}",
        "link": "/schedule",
    }


# ── 랭킹 ──
def ranking_winner(period: str, label: str) -> dict:
    # label = "종합왕"|"매출왕"…
    return {"type": "RANKING", "title": f"{label}에 뽑혔어요 🏆", "body": f"지난달 {period} 1위예요. 축하해요!", "link": "/ranking"}


def ranking_announce(period: str, summary: str) -> dict:
    return {"type": "RANKING", "title": f"{period} 랭킹이 나왔어요 📢", "body": summary, "link": "/ranking"}


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
    return {"type": "ATTENDANCE", "title": f"{name}님이 {action}했어요", "body": body, "link": "/attendance"}


def my_task_missing(left: list[str]) -> dict:
    """본인에게 — 내 업무를 남기고 퇴근했다.

    **`MY_TASK` 가 아니라 `MY_TASK_MISSING` 이다** (2026-08-21). 앱이 이것만
    빨간 경고로 그린다. 같은 `MY_TASK` 에 수정·삭제 결재와 **승인** 알림이
    섞여 있어서, 종류째 빨갛게 하면 승인받은 것도 경고로 보인다.

    옛 앱은 모르는 종류를 회색으로 떨구므로 지금과 똑같이 보인다 — 안 깨진다.
    """
    head = left[0] if left else ""
    body = head if len(left) == 1 else f"{head} 외 {len(left) - 1}개"
    return {
        "type": "MY_TASK_MISSING",
        "title": "안 한 업무가 있어요",
        "body": f"{body}를 아직 못 했어요",
        "link": "/work",
    }


def staff_task_missing(name: str, left: int) -> dict:
    """대표에게 — 누가 업무를 남기고 퇴근했다.

    본인 것과 **같이 빨갛게** 뜬다 (2026-08-21 대표 요청).
    """
    return {
        "type": "MY_TASK_MISSING",
        "title": f"{name}님이 업무를 남기고 퇴근했어요",
        "body": f"내 업무 {left}개가 안 됐어요",
        "link": "/work",
    }


def task_miss_confirmed(day, contents: list[str]) -> dict:
    """본인에게 — 다음 근무일까지도 안 해서 **확정 누락**이 됐다 (2026-08-21).

    퇴근할 때 온 알림과 글이 갈려야 한다. 저쪽은 '아직 기회가 있다' 는 뜻이고
    이쪽은 이미 깎였다는 뜻이라, 같은 문장이면 회복할 수 있는 날을 놓친다.
    """
    head = contents[0] if contents else ""
    body = head if len(contents) == 1 else f"{head} 외 {len(contents) - 1}개"
    return {
        "type": "MY_TASK_MISSING",
        "title": f"{day.month}월 {day.day}일 업무가 누락됐어요",
        "body": f"{body} · 사유가 있으면 사유서를 내 주세요",
        "link": "/work",
    }


def task_miss_excuse(name: str, day) -> dict:
    """대표에게 — 누락 사유서가 올라왔다 (2026-08-21).

    **`MY_TASK` 다.** 결재 요청이지 경고가 아니라, 빨간 종류로 보내면
    대표 알림함이 빨간 줄로 도배된다.
    """
    return {
        "type": "MY_TASK",
        "title": "업무 누락 사유서",
        "body": f"{name} · {day.month}월 {day.day}일",
        "link": "/work",
    }


def task_miss_decided(day, approve: bool, reason: str | None) -> dict:
    """본인에게 — 사유서가 처리됐다. 승인이면 깎였던 점수가 되돌아온다."""
    head = f"{day.month}월 {day.day}일 누락"
    if approve:
        return {
            "type": "MY_TASK",
            "title": f"{head} 사유가 승인됐어요",
            "body": "깎인 점수가 되돌아왔어요",
            "link": "/work",
        }
    return {
        "type": "MY_TASK_MISSING",
        "title": f"{head} 사유가 반려됐어요",
        "body": reason or "",
        "link": "/work",
    }


def staff_absent(name: str) -> dict:
    return {
        "type": "ATTENDANCE",
        "title": f"{name}님이 안 나왔어요",
        "body": "퇴근 시간이 지나도록 출근 기록이 없어요",
        "link": "/attendance",
    }


# ---------------------------------------------------------------------------
# 출퇴근 단말 (2026-08-26) — 대표에게만
# ---------------------------------------------------------------------------
#
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
        "body": f"{short(project_title, 30)} · {author_name}",
        "link": _project_link(project_id),
    }


def project_completed(project_title: str, project_id: str | None = None) -> dict:
    return {
        "type": "PROJECT",
        "title": "프로젝트가 완료됐어요",
        "body": short(project_title),
        "link": _project_link(project_id),
    }


def project_overdue_admin(project_title: str, who: str, project_id: str | None = None) -> dict:
    return {
        "type": "PROJECT",
        "title": "프로젝트가 누락됐어요",
        "body": f"{short(project_title, 30)} · {who}",
        "link": _project_link(project_id),
    }


def meeting_created(meeting_title: str, author_name: str, meeting_id: str) -> dict:
    return {
        "type": "MEETING",
        "title": "새 회의록이 올라왔어요",
        "body": f"{short(meeting_title, 30)} · {author_name}",
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
    return {"type": "STAFF", "title": f"{name}님이 퇴사했어요", "body": None, "link": "/staff"}


#: 업무 상태 → 알림에 그대로 들어가는 **한 마디**
#:
#: 이름 뒤에 붙여 `윤서연님이 외출중이에요` 가 되게 문장으로 적어 둔다.
#: 라벨만 두고 `{라벨} 상태로 바꿨어요` 로 짜면 `외출 상태로 바꿨어요` 처럼
#: 어색해진다 (2026-08-20 대표 요청으로 문장으로 바꿨다).
#:
#: `AUTO` 는 "따로 정하지 않음"이라 **되돌린 것**으로 읽히게 적는다 —
#: 앱 고르개의 `자동 (출근 기준)` 을 그대로 쓰면 알림에서는 무슨 말인지 모른다.
#: `AWAY` 만 `~중이에요` 가 안 붙어서 따로 적는다.
_WORK_STATUS_LINES = {
    "AUTO": "근무 중이에요",
    "MEETING": "회의중이에요",
    "MEAL": "식사중이에요",
    "OUT": "외출중이에요",
    "AWAY": "자리를 비웠어요",
}


def work_status_changed(name: str, status, message: str | None) -> dict:
    """직원이 업무 상태·상태 메시지를 바꿨다 — **대표·관리자에게만** (2026-08-20 요청).

    조직도 상태 점이 바뀌는 것을 아무도 모르고 지나가서, 자리를 비운 사람이
    생겨도 대표가 조직도를 열어 봐야만 알았다.

    본인은 뺀다(`notify_bosses(exclude=...)`) — 자기가 방금 누른 것이다.
    """
    # 모르는 값이면 상태를 짚지 않고 바뀌었다고만 한다 (enum 이 늘어도 안 깨진다)
    line = _WORK_STATUS_LINES.get(str(status), "상태를 바꿨어요")
    note = (message or "").strip()
    return {
        "type": "STAFF",
        "title": f"{name}님이 {line}",
        # 상태 메시지는 **선택**이다 — 안 적었으면 제목 한 줄로 끝난다
        "body": short(note) if note else None,
        "link": "/staff",
    }


def env_award(item: str, total: int, reason: str | None) -> dict:
    """가산점을 받은 사람에게 — 대표가 블로그 점수를 매겼다 (2026-08-28).

    **`SCORE` 다.** 결재도 경고도 아니고 점수가 바뀌었다는 알림이다.

    `total` 은 기본 배점까지 더한 **최종 점수**다. 가산분만 적으면
    `+7` 인데 화면의 기록 줄에는 `10` 이 떠서 두 숫자가 어긋난다.
    """
    return {
        "type": "SCORE",
        "title": f"{item} 점수가 {total}점이 됐어요",
        "body": reason,
        "link": "/work",
    }


def score_reverted(points: int, reason: str | None) -> dict:
    """깎였던 점수를 대표가 되돌렸다 (2026-08-28).

    **`SCORE` 다.** 깎을 때(`late_penalty`·`task_miss_confirmed`)는 경고 쪽인데
    되돌리는 것은 좋은 소식이라 같은 종류로 보내면 안 된다.
    """
    return {
        "type": "SCORE",
        "title": f"깎였던 {abs(points)}점이 돌아왔어요",
        "body": reason,
        "link": "/work",
    }


def kindness_praise(member_name: str, comment: str) -> dict:
    """칭찬을 받은 본인에게 (2026-08-31 대표 요청).

    **`SCORE` 가 아니다.** 같이 붙는 KINDNESS 10점보다 칭찬 자체가 본론이라
    점수 알림과 섞이면 안 된다.
    """
    return {
        "type": "KINDNESS",
        "title": "칭찬을 받았어요 🎉",
        "body": f"{member_name}님 · {short(comment)}",
        "link": "/work",
    }


def kindness_praise_boss(name: str, comment: str) -> dict:
    """직원이 칭찬받았다 — 대표·관리자에게."""
    return {
        "type": "KINDNESS",
        "title": f"{name}님이 칭찬받았어요",
        "body": short(comment),
        "link": "/work",
    }


def kindness_complaint(improvement: str, branch: str | None) -> dict:
    """컴플레인이 들어왔다 (2026-08-31 대표 요청).

    [branch] 는 **전 지점을 받는 사람(MASTER·ADMIN)에게만** 채운다. 자기
    지점 것만 받는 사람에게는 뻔한 말이라 자리만 먹는다.
    """
    body = short(improvement)
    return {
        "type": "COMPLAINT",
        "title": "컴플레인이 들어왔어요",
        "body": f"{branch} · {body}" if branch else body,
        "link": "/work",
    }


def kindness_resolved(resolver: str, improvement: str, branch: str | None) -> dict:
    """컴플레인이 해결됐다 — **누가 처리했는지**가 본론이다 (2026-08-31)."""
    body = f"{resolver}님이 처리했어요 · {short(improvement)}"
    return {
        "type": "COMPLAINT",
        "title": "컴플레인이 해결됐어요",
        "body": f"{branch} · {body}" if branch else body,
        "link": "/work",
    }
