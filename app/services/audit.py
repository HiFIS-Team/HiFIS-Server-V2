"""활동 로그 — 주소를 사람 말로 옮기고, 남기면 안 되는 값을 가린다.

미들웨어(`app/core/audit_middleware.py`)와 조회 API 가 같이 쓴다.
"""

import re

# ---------------------------------------------------------------------------
# 주소 정규화
# ---------------------------------------------------------------------------

# 우리 id 는 전부 uuid4 문자열(36자)이라 이것만 {id} 로 바꾼다.
# 'me' · 'tree' · 'read-all' 같은 고정 조각은 그대로 둬야 라벨이 갈린다.
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def normalize(path: str) -> str:
    """`/projects/abc-…/todos/def-…` → `/projects/{id}/todos/{id}`

    **uuid 가 아닌 식별자도 접어야 한다.** 회원 설문(`/survey/{지점토큰}`)이
    그렇다 — 토큰이 `secrets.token_urlsafe` 라 uuid 모양이 아니어서, 안 접으면
    지점마다 다른 주소로 남고 SKIP·NO_PAYLOAD·LABELS 가 하나도 안 걸린다.
    그러면 **손님의 이름·연락처가 본문째 로그에 쌓인다.**
    """
    parts = [("{id}" if _UUID.match(seg) else seg) for seg in path.split("/")]
    if len(parts) > 2 and parts[1] == "survey":
        parts[2] = "{id}"
    return "/".join(parts)


# ---------------------------------------------------------------------------
# 안 남기는 것
# ---------------------------------------------------------------------------

# 읽음 처리·구독처럼 사람이 '한 일'이 아니면서 양만 많은 것들.
# 로그인은 접속 로그(access_logs)에 이미 있고 본문에 비밀번호가 들어 있어 뺀다.
SKIP: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/auth/login"),
        ("POST", "/auth/refresh"),
        ("POST", "/notices/{id}/read"),
        ("POST", "/chat/rooms/{id}/read"),
        ("POST", "/notifications/read-all"),
        ("POST", "/notifications/{id}/read"),
        ("POST", "/push/subscribe"),
        ("DELETE", "/push/subscribe"),
        ("POST", "/documents/{id}/favorite"),
        ("DELETE", "/documents/{id}/favorite"),
    }
)


# 줄은 남기되 **본문은 안 담는** 것들.
# 대화는 `chat_messages` 에 통째로 남아 있고 열람 화면(/audit/chat)이 따로 있다.
# 여기까지 본문을 담으면 사내톡이 두 벌로 쌓인다 — 제일 양이 많은 자리다.
NO_PAYLOAD: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/chat/rooms/{id}/messages"),
        # 회원 설문 — 손님의 이름·연락처가 본문에 있다. 설문 표에 이미 들어가 있고
        # 여기까지 담으면 **직원이 아닌 사람의 개인정보가 두 벌**로 쌓인다
        ("POST", "/survey/{id}"),
    }
)

#: 본문 대신 남길 한 줄 — **왜 안 남겼는지**가 보여야 나중에 안 헷갈린다
NO_PAYLOAD_NOTE: dict[str, str] = {
    "/chat/rooms/{id}/messages": "대화 내용은 사내톡 열람에서 봐요",
    "/survey/{id}": "회원 개인정보라 본문은 설문 목록에서만 봐요",
}


# GET 인데도 남기는 것 — **감시하는 쪽을 감시한다.**
# 남의 대화를 열어 본 일은 그 자체가 기록으로 남아야 한다
# (개인정보처리방침 §8-1 에 그렇게 적어 뒀다). 관리자만 부르는 주소라 양도 적다.
READ_LOGGED: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/access-logs"),
        ("GET", "/audit-logs"),
        ("GET", "/audit/chat/rooms"),
        ("GET", "/audit/chat/rooms/{id}/messages"),
        ("GET", "/audit/chat/messages"),
    }
)


# ---------------------------------------------------------------------------
# 마스킹
# ---------------------------------------------------------------------------

# 남으면 안 되는 값 — 키 이름으로 가른다(camel·snake 둘 다 온다)
_SECRET_KEYS = frozenset(
    {
        "password",
        "currentPassword",
        "current_password",
        "newPassword",
        "new_password",
        "passwordHash",
        "password_hash",
        "token",
        "resetToken",
        "reset_token",
        "accessToken",
        "access_token",
        "refreshToken",
        "refresh_token",
        "code",  # 비밀번호 재설정 인증번호
        "signatureBase64",  # 회원 전자서명 원본
        "signature_base64",
    }
)

MASK = "***"


def mask(value):
    """비밀 키를 `***` 로 바꾼 사본을 돌려준다 (원본은 안 건드린다)"""
    if isinstance(value, dict):
        return {k: (MASK if k in _SECRET_KEYS else mask(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# 한국어 라벨
# ---------------------------------------------------------------------------

# (메서드, 정규화된 주소) → 화면에 뜰 말.
# 새 엔드포인트를 만들면 여기에도 한 줄 넣는다. 빠지면 주소가 그대로 보인다.
LABELS: dict[tuple[str, str], str] = {
    # 계정·인증
    ("POST", "/auth/signup"): "회원가입",
    ("POST", "/auth/logout"): "로그아웃",
    ("POST", "/auth/password-reset/request"): "비밀번호 재설정 요청",
    ("POST", "/auth/password-reset/verify"): "비밀번호 재설정 인증",
    ("POST", "/auth/password-reset/confirm"): "비밀번호 재설정 완료",
    # 직원·조직
    ("POST", "/employees"): "직원 추가",
    ("PATCH", "/employees/me"): "내 프로필 수정",
    ("POST", "/employees/me/avatar"): "프로필 사진 변경",
    ("POST", "/employees/me/password"): "비밀번호 변경",
    ("POST", "/employees/me/schedule"): "근무 설정 변경",
    ("POST", "/employees/me/consents"): "약관 동의",
    ("POST", "/employees/me/withdraw"): "탈퇴",
    ("PATCH", "/employees/{id}"): "인사 정보 변경",
    ("DELETE", "/employees/{id}"): "직원 삭제",
    ("POST", "/invite-keys"): "초대키 발급",
    ("DELETE", "/invite-keys/{id}"): "초대키 삭제",
    ("POST", "/branches"): "지점 추가",
    ("PATCH", "/branches/{id}"): "지점 수정",
    # 근태·월차
    ("POST", "/attendance/scan"): "출퇴근 기록",
    ("POST", "/leaves"): "월차 신청",
    ("POST", "/leaves/{id}/approve"): "월차 승인",
    ("POST", "/leaves/{id}/reject"): "월차 반려",
    ("POST", "/leaves/{id}/cancel"): "월차 취소",
    # 급여
    ("POST", "/payslips/generate"): "급여 산출",
    ("POST", "/payslips/me/submit"): "급여 신청",
    ("POST", "/payslips/me/cancel"): "급여 신청 취소",
    ("POST", "/payslips/{id}/approve"): "급여 승인",
    ("POST", "/payslips/{id}/reject"): "급여 반려",
    ("POST", "/payslips/{id}/pay"): "급여 지급 처리",
    ("POST", "/rank-policies"): "직급 급여 기준 추가",
    ("DELETE", "/rank-policies/{id}"): "직급 급여 기준 삭제",
    # 회원·수업
    ("POST", "/members"): "회원 등록",
    ("PATCH", "/members/{id}"): "회원 정보 수정",
    ("POST", "/members/{id}/consents"): "회원 동의 기록",
    ("POST", "/registrations"): "등록권 발급",
    ("POST", "/session-signs"): "세션 싸인",
    # 점수
    ("POST", "/scores"): "점수 부여",
    ("POST", "/contributions"): "기여 점수 부여",
    ("POST", "/env-items"): "환경정비 항목 추가",
    ("PATCH", "/env-items/{id}"): "환경정비 항목 수정",
    ("POST", "/env-logs"): "환경정비 수행",
    ("DELETE", "/env-logs/{id}"): "환경정비 취소",
    ("POST", "/supply-orders"): "비품 주문",
    ("POST", "/peer-reviews"): "동료 평가 제출",
    ("PATCH", "/kindness-surveys/{id}/status"): "컴플레인 처리 단계 변경",
    ("POST", "/webhooks/kindness-survey"): "회원 설문 접수",
    ("POST", "/survey/{id}"): "회원 설문 접수(매장 QR)",
    # 프로젝트
    ("POST", "/projects"): "프로젝트 만들기",
    ("PATCH", "/projects/{id}"): "프로젝트 수정",
    ("DELETE", "/projects/{id}"): "프로젝트 삭제",
    ("POST", "/projects/{id}/award"): "프로젝트 점수 조정",
    ("POST", "/projects/{id}/comments"): "프로젝트 댓글",
    ("PATCH", "/projects/{id}/comments/{id}"): "프로젝트 댓글 수정",
    ("DELETE", "/projects/{id}/comments/{id}"): "프로젝트 댓글 삭제",
    ("POST", "/projects/{id}/todos"): "할 일 추가",
    ("PATCH", "/projects/{id}/todos/{id}"): "할 일 수정",
    ("DELETE", "/projects/{id}/todos/{id}"): "할 일 삭제",
    ("POST", "/projects/{id}/requests"): "기한 연장 신청",
    ("POST", "/projects/requests/{id}/approve"): "기한 연장 승인",
    ("POST", "/projects/requests/{id}/reject"): "기한 연장 반려",
    ("POST", "/todos"): "할 일 추가",
    ("PATCH", "/todos/{id}"): "할 일 수정",
    # 협업
    ("POST", "/notices"): "공지 작성",
    ("PATCH", "/notices/{id}"): "공지 수정",
    ("DELETE", "/notices/{id}"): "공지 삭제",
    ("POST", "/meetings"): "회의록 작성",
    ("PATCH", "/meetings/{id}"): "회의록 수정",
    ("DELETE", "/meetings/{id}"): "회의록 삭제",
    ("POST", "/events"): "일정 추가",
    ("PATCH", "/events/{id}"): "일정 수정",
    ("DELETE", "/events/{id}"): "일정 삭제",
    ("POST", "/events/{id}/approve"): "일정 승인",
    ("POST", "/events/{id}/reject"): "일정 반려",
    ("POST", "/reactions"): "이모지 반응",
    # 전자결재
    ("POST", "/approvals"): "결재 올리기",
    ("POST", "/approvals/{id}/approve"): "결재 승인",
    ("POST", "/approvals/{id}/reject"): "결재 반려",
    ("POST", "/approvals/{id}/withdraw"): "결재 회수",
    ("POST", "/approvals/{id}/comments"): "결재 댓글",
    # 사내톡
    ("POST", "/chat/rooms"): "대화방 만들기",
    ("PATCH", "/chat/rooms/{id}"): "대화방 이름 변경",
    ("POST", "/chat/rooms/{id}/members"): "대화방 초대",
    ("DELETE", "/chat/rooms/{id}/members/me"): "대화방 나가기",
    ("POST", "/chat/rooms/{id}/messages"): "메시지 보내기",
    ("DELETE", "/chat/rooms/{id}/messages/{id}"): "메시지 전송 취소",
    ("POST", "/chat/rooms/{id}/attachments"): "파일 보내기",
    ("PATCH", "/chat/rooms/{id}/mute"): "대화방 알림 설정",
    # 문서함
    ("POST", "/documents"): "문서 올리기",
    ("PATCH", "/documents/{id}"): "문서 수정",
    ("DELETE", "/documents/{id}"): "문서 삭제",
    ("POST", "/folders"): "폴더 만들기",
    ("POST", "/folders/tree"): "폴더 통째로 올리기",
    ("PATCH", "/folders/{id}"): "폴더 수정",
    ("DELETE", "/folders/{id}"): "폴더 삭제",
    # 보안
    ("POST", "/security/capture"): "화면 캡처",
    # 열람 (READ_LOGGED)
    ("GET", "/access-logs"): "접속 기록 열람",
    ("GET", "/audit-logs"): "활동 기록 열람",
    ("GET", "/audit/chat/rooms"): "대화방 목록 열람",
    ("GET", "/audit/chat/rooms/{id}/messages"): "대화 열람",
    ("GET", "/audit/chat/messages"): "메시지 검색",
}


def label(method: str, route: str) -> str:
    """모르는 주소는 `POST /foo` 그대로 — 라벨표에 빠진 걸 눈치채라고 감추지 않는다"""
    return LABELS.get((method, route)) or f"{method} {route}"
