"""문자(SMS) 발송 — 솔라피. **부르는 곳 둘이 같이 쓴다.**

| 부르는 곳 | 받는 사람 | 발신번호 |
|---|---|---|
| 비밀번호 재설정 (`password_reset.py`) | 직원 | `settings.solapi_sender` (기본) |
| 컴플레인 해결 알림 (`api/scoring/kindness.py`) | **회원** | **그 지점 번호** (`branches.sms_sender`) |

## 왜 발신번호를 갈라 쓰나 (2026-09-08 대표 결정)

컴플레인 문자는 **회원이 받는 것**이라, 회원이 그 번호로 되걸면 그 매장에
닿아야 한다. 본사 번호로 보내면 화순 회원이 첨단 일로 전화하는 셈이 된다.

비밀번호 재설정은 **로그인 전**이라 그 사람이 어느 지점인지 모른다. 그래서
그쪽만 기본 번호를 쓴다.

## 발신번호는 사전등록·인증이 끝난 것이어야 한다

전기통신사업법이다. 솔라피 콘솔에 등록 안 된 번호를 넣으면 **발송이 통째로
거부된다** — 코드가 맞아도 안 나간다.
"""

import logging
import time

from app.core.config import settings

logger = logging.getLogger(__name__)

#: 솔라피 일시 오류 재시도 — v1 과 같은 횟수
RETRIES = 3
RETRY_WAIT_S = 1


def mask_phone(phone: str) -> str:
    """로그에 남길 번호 — 가운데를 가린다 (`01012345678` → `010****5678`).

    발송 성공·실패는 남겨야 되짚을 수 있는데, 번호를 그대로 적으면 로그가
    개인정보 덩어리가 된다 (개인정보처리방침 §8-1 과 같은 맥락).
    """
    digits = "".join(c for c in (phone or "") if c.isdigit())
    return f"{digits[:3]}****{digits[-4:]}" if len(digits) >= 7 else "***"


def ready(sender: str | None = None) -> bool:
    """보낼 수 있나 — 열쇠 둘과 **발신번호**가 다 있어야 한다.

    [sender] 를 주면 그 번호로 보낼 수 있는지를 본다 (지점 번호). 안 주면
    기본 번호(`settings.solapi_sender`)를 본다.
    """
    return bool(
        settings.solapi_api_key
        and settings.solapi_api_secret
        and (sender or settings.solapi_sender)
    )


def send_sync(
    to: str,
    text: str,
    *,
    sender: str | None = None,
    subject: str | None = None,
    tag: str = "sms",
) -> None:
    """솔라피 발송(블로킹) — `asyncio.to_thread` 로 감싸 이벤트 루프를 안 막는다.

    HiFIS v1(`app/services/messaging/solapi.py`)이 쓰던 공식 SDK 그대로다.

    **90바이트를 넘으면 LMS 로 나가 건당 요금이 두 배 이상이다.** 인증번호
    한 줄은 40바이트 남짓이라 SMS 로 나가고, 컴플레인 알림은 매장 이름과
    의견이 들어가서 LMS 다 (그건 알고 그렇게 두는 것이다 — 무슨 의견이
    반영됐는지가 안 적히면 받는 사람이 무슨 문자인지 모른다).

    [subject] 는 **LMS 제목**이다. 안 주면 통신사가 본문 앞머리를 잘라서 제목을
    만드는데, 그러면 알림에 `[피트니스스타 화순점] 남겨주신 의견이` 처럼
    문장이 끊겨 뜬다 (실제로 그렇게 왔다). 90바이트 이하 SMS 에서는 무시된다.

    [tag] 는 로그 앞머리다. 두 곳이 같이 쓰는 함수라 어느 쪽 문자가 실패했는지
    로그에서 갈려야 한다.
    """
    from solapi import SolapiMessageService
    from solapi.model import RequestMessage

    client = SolapiMessageService(
        api_key=settings.solapi_api_key,
        api_secret=settings.solapi_api_secret,
    )
    fields = {"from_": sender or settings.solapi_sender, "to": to, "text": text}
    if subject:
        fields["subject"] = subject
    message = RequestMessage(**fields)

    last: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            client.send(message)
            logger.info("[%s] 문자 발송 완료 to=%s attempt=%d", tag, mask_phone(to), attempt)
            return
        except Exception as error:  # noqa: BLE001 — 마지막 시도까지 모아 두고 올린다
            last = error
            logger.warning(
                "[%s] 문자 발송 실패 to=%s attempt=%d error=%s",
                tag, mask_phone(to), attempt, error,
            )
            if attempt < RETRIES:
                time.sleep(RETRY_WAIT_S)
    raise last if last else RuntimeError("문자 발송 실패")


__all__ = ["mask_phone", "ready", "send_sync", "RETRIES"]
