"""비밀번호 재설정 — 인증번호 발급/검증 + 단일 사용 재설정 토큰 (CLAUDE.md §2.3, §9.7).

- 프론트 auth_reset.dart 3단계: ①대상 입력(이메일/전화) ②6자리 인증번호 ③새 비번.
- 인증번호·재설정 토큰은 Redis 에 TTL 로 저장 → 서버 재시작·멀티워커에도 안전.
- 발송: EMAIL 은 SMTP, PHONE 은 솔라피 SMS. **설정이 비었거나 실패하면 로그 폴백**(개발).
- 사용자 열거(enumeration) 방지: request 엔드포인트는 대상 유무와 무관하게 항상 성공 응답.
"""

import asyncio
import json
import logging
import re
import secrets
import time

from fastapi import HTTPException

from app.core.config import settings
from app.core.redis import get_redis
from app.core.security import create_reset_token, decode_token

logger = logging.getLogger("app.password_reset")

CODE_TTL_S = 180        # 인증번호 유효 3분 (프론트 재전송 타이머와 일치)
SEND_COOLDOWN_S = 60    # 동일 대상 재발송 최소 간격(스팸 억제, 무해)
MAX_ATTEMPTS = 5        # 인증번호 검증 최대 시도(무차별 대입 방지)


def _code_key(contact: str) -> str:
    return f"pwreset:code:{contact}"


def _cooldown_key(contact: str) -> str:
    return f"pwreset:cd:{contact}"


def _rt_key(jti: str) -> str:
    return f"pwreset:rt:{jti}"


def normalize_contact(contact: str) -> tuple[str, str]:
    """(method, 정규화된 contact) — '@' 있으면 EMAIL, 아니면 PHONE(숫자만).

    request/verify 양쪽에서 동일 정규화 → 코드 키가 일치한다(verify 는 method 를 안 받음).
    """
    c = (contact or "").strip()
    if "@" in c:
        return "EMAIL", c
    return "PHONE", re.sub(r"\D", "", c)


def generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _send_email_sync(to: str, subject: str, body: str) -> None:
    """SMTP 발송(블로킹) — asyncio.to_thread 로 감싸 이벤트 루프 비차단. 저빈도라 충분."""
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as s:
        if settings.smtp_starttls:
            s.starttls()
        if settings.smtp_user:
            s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)


SMS_RETRIES = 3         # 솔라피 일시 오류 재시도 (v1 과 같은 횟수)
SMS_RETRY_WAIT_S = 1


def _mask_phone(phone: str) -> str:
    """로그에 남길 번호 — 가운데를 가린다 (`01012345678` → `010****5678`).

    발송 성공·실패는 남겨야 되짚을 수 있는데, 번호를 그대로 적으면 로그가
    개인정보 덩어리가 된다 (개인정보처리방침 §8-1 과 같은 맥락).
    """
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else "***"


def _sms_ready() -> bool:
    """셋이 다 있어야 보낸다 — 하나라도 비면 솔라피가 인증부터 실패한다."""
    return bool(
        settings.solapi_api_key and settings.solapi_api_secret and settings.solapi_sender
    )


def _send_sms_sync(to: str, text: str) -> None:
    """솔라피 발송(블로킹) — asyncio.to_thread 로 감싸 이벤트 루프 비차단.

    HiFIS v1(`app/services/messaging/solapi.py`)이 쓰던 공식 SDK 그대로다.
    같은 계정·같은 발신번호라 v1 에서 되던 것이 여기서도 된다.

    **본문을 짧게 유지한다.** 90바이트를 넘으면 SMS 가 아니라 LMS 로 나가서
    건당 요금이 두 배 이상이 된다. 인증번호 한 줄이면 40바이트 남짓이다.
    """
    from solapi import SolapiMessageService
    from solapi.model import RequestMessage

    client = SolapiMessageService(
        api_key=settings.solapi_api_key,
        api_secret=settings.solapi_api_secret,
    )
    message = RequestMessage(from_=settings.solapi_sender, to=to, text=text)

    last: Exception | None = None
    for attempt in range(1, SMS_RETRIES + 1):
        try:
            client.send(message)
            logger.info(
                "[password-reset] 문자 발송 완료 to=%s attempt=%d", _mask_phone(to), attempt
            )
            return
        except Exception as error:  # noqa: BLE001 — 마지막 시도까지 모아 두고 올린다
            last = error
            logger.warning(
                "[password-reset] 문자 발송 실패 to=%s attempt=%d error=%s",
                _mask_phone(to), attempt, error,
            )
            if attempt < SMS_RETRIES:
                time.sleep(SMS_RETRY_WAIT_S)
    raise last if last else RuntimeError("문자 발송 실패")


async def send_reset_code(method: str, contact: str, code: str) -> None:
    """인증번호 발송 — EMAIL 은 SMTP, PHONE 은 솔라피 SMS. 미설정·실패는 로그 폴백.

    폴백이 있는 이유는 **개발 중에 계정 없이도 흐름을 태울 수 있어야** 해서다
    (`docker compose logs api | grep password-reset` 로 코드를 꺼내 쓴다).
    운영에서 설정이 비어 있으면 사용자는 인증번호를 영영 못 받으므로,
    폴백으로 떨어질 때는 WARNING 을 남겨 눈에 띄게 한다.
    """
    if method == "EMAIL" and settings.smtp_host:
        try:
            await asyncio.to_thread(
                _send_email_sync,
                contact,
                "[HiFIS] 비밀번호 재설정 인증번호",
                f"인증번호는 {code} 입니다. 3분 안에 입력해 주세요.\n\n요청하지 않으셨다면 이 메일을 무시하세요.",
            )
            logger.info("[password-reset] 이메일 발송 완료 contact=%s", contact)
            return
        except Exception:
            logger.exception("[password-reset] 이메일 발송 실패 — 로그 폴백")

    if method == "PHONE" and _sms_ready():
        try:
            await asyncio.to_thread(
                _send_sms_sync, contact, f"[HiFIS] 인증번호 {code} (3분 내 입력)"
            )
            return
        except Exception:
            logger.exception("[password-reset] 문자 발송 실패 — 로그 폴백")

    # 폴백: 개발/미설정/실패 — 코드를 눈으로 확인하도록 WARNING 으로 남긴다.
    logger.warning("[password-reset] 발송 스텁(실제 발송 아님) method=%s contact=%s code=%s", method, contact, code)


async def issue_code(contact: str, employee_id: str) -> None:
    """인증번호 생성·저장·발송. 쿨다운 중이면 조용히 스킵(응답은 동일하게 성공)."""
    method, norm = normalize_contact(contact)
    r = get_redis()
    if await r.get(_cooldown_key(norm)):  # 최근 발송됨 → 재발송 억제
        return
    code = generate_code()
    await r.set(
        _code_key(norm),
        json.dumps({"code": code, "employee_id": employee_id, "attempts": 0}),
        ex=CODE_TTL_S,
    )
    await r.set(_cooldown_key(norm), "1", ex=SEND_COOLDOWN_S)
    await send_reset_code(method, norm, code)


async def verify_code(contact: str, code: str) -> str | None:
    """인증번호 검증 성공 시 재설정 토큰 반환, 실패 시 None.

    성공하면 코드는 즉시 소비(삭제)되고, 단일 사용 jti 를 Redis 에 심어 토큰을 발급한다.
    """
    _, norm = normalize_contact(contact)
    r = get_redis()
    key = _code_key(norm)
    raw = await r.get(key)
    if not raw:
        return None
    data = json.loads(raw)
    data["attempts"] = int(data.get("attempts", 0)) + 1
    if data["attempts"] > MAX_ATTEMPTS:
        await r.delete(key)
        return None
    if not secrets.compare_digest(str(data.get("code", "")), str(code or "")):
        ttl = await r.ttl(key)  # 남은 유효시간 유지하며 시도횟수만 갱신
        await r.set(key, json.dumps(data), ex=ttl if ttl and ttl > 0 else CODE_TTL_S)
        return None
    # 성공 → 코드 소비 + 단일 사용 토큰 발급
    await r.delete(key)
    jti = secrets.token_urlsafe(16)
    await r.set(_rt_key(jti), data["employee_id"], ex=settings.password_reset_token_expire_minutes * 60)
    return create_reset_token(data["employee_id"], jti)


async def consume_reset_token(token: str) -> str:
    """재설정 토큰 검증 + 단일 사용 소비 → employee_id. 무효/만료/재사용이면 400."""
    payload = decode_token(token, expected_type="pwreset")  # 서명·타입·만료 불량이면 401
    jti = payload.get("jti")
    sub = payload.get("sub")
    r = get_redis()
    stored = await r.getdel(_rt_key(jti)) if jti else None  # 소비(단일 사용)
    if stored is None or stored != sub:
        raise HTTPException(
            400,
            detail={"code": "INVALID_RESET_TOKEN", "message": "재설정 토큰이 유효하지 않거나 만료되었습니다"},
        )
    return sub
