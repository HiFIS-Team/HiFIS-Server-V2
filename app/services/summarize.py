"""컴플레인 한 줄 요약 — Claude Messages API (2026-09-08 대표 요청).

매장 TV 는 컴플레인 한 줄을 **두 줄까지만** 그리고 나머지를 자른다
(`HiFIS-Client-V2` 의 `tv.css` — `-webkit-line-clamp:2`). 회원이 길게 적으면
벽에 `...` 로 끊긴 문장이 걸린다.

그래서 **해결 완료로 넘어가는 순간 한 줄로 줄여 `kindness_surveys.summary`
에 박아 둔다.** TV 는 그 줄이 있으면 그걸 쓴다.

## 왜 저장하나 — 화면이 부를 때 요약하면 안 된다

TV 는 몇 분마다 다시 받는다. 그때마다 부르면

- 느리고 (요청마다 왕복이 하나 는다)
- **문장이 저 혼자 바뀐다** — 같은 컴플레인인데 새로고침할 때마다 다른 말이
  걸린다. 추첨 당첨자를 화면에서 안 뽑고 행에 박아 두는 것과 같은 이유다

## 실패하면 원문을 쓴다

키가 없거나 API 가 죽어도 **해결 처리는 그대로 끝나야 한다.** 요약은 곁가지라
못 만들면 `None` 을 돌려주고, TV 는 예전처럼 원문을 그린다.

새 의존성이 없다 — `httpx` 는 APNs 때문에 이미 들어 있다.
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_URL = "https://api.anthropic.com/v1/messages"
_VERSION = "2023-06-01"

#: 기다리는 시간(초) — 해결 완료 버튼이 이만큼 늦어질 수 있다는 뜻이다.
#: 한 줄 요약이라 보통 1초 안에 오고, 넘어가면 원문으로 떨어진다.
_TIMEOUT_S = 8.0

#: 뽑을 최대 토큰 — 한 줄이라 넉넉히 잡아도 이 정도다
_MAX_TOKENS = 200

#: 이보다 짧으면 **부르지 않는다** — 이미 한 줄이라 줄일 것이 없다.
#: TV 가 두 줄까지 그리므로 그 안에 드는 길이는 그대로 두는 것이 낫다
#: (회원이 쓴 말을 굳이 바꾸지 않는다).
MIN_LEN = 40

_SYSTEM = (
    "너는 헬스장 회원이 남긴 의견을 매장 TV 에 걸 한 줄로 줄이는 일을 한다.\n"
    "\n"
    "규칙\n"
    "- 한국어 한 문장, 공백 포함 35자 이내\n"
    "- 회원이 말한 내용만 쓴다. 없는 말을 지어내지 않는다\n"
    "- 회원이 쓴 말투와 높임을 살린다 (예: '~해요', '~면 좋겠어요')\n"
    "- 여러 이야기가 섞여 있으면 **가장 중요한 하나만** 남긴다\n"
    "- 따옴표·말줄임표·앞뒤 설명을 붙이지 않는다. 요약문만 답한다\n"
    "- 사람 이름·연락처는 넣지 않는다\n"
    "\n"
    "예시\n"
    "입력: 회원들중에 한분이 기구사용후 정리를 몇달동안 안하시니 다른회원분들과 "
    "저도 너무 불편합니다 조치를 부탁드립니다\n"
    "출력: 기구 정리를 안 하는 회원이 있어 불편해요\n"
)


async def summarize_complaint(text: str) -> str | None:
    """컴플레인 한 줄 요약 — **못 만들면 `None`.**

    부르는 쪽은 돌려받은 값이 있을 때만 저장하고, 없으면 원문을 그대로 둔다.
    """
    clean = (text or "").strip()
    if not clean:
        return None
    if not settings.anthropic_api_key:
        logger.info("[complaint-summary] 키가 없어 건너뜀 — TV 는 원문을 쓴다")
        return None
    # 짧은 것은 안 줄인다 — 회원이 쓴 말 그대로가 낫다
    if len(clean) <= MIN_LEN:
        return None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            res = await client.post(
                _URL,
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": _VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": settings.anthropic_model,
                    "max_tokens": _MAX_TOKENS,
                    "system": _SYSTEM,
                    "messages": [{"role": "user", "content": clean}],
                },
            )
            res.raise_for_status()
            data = res.json()
    except Exception:
        logger.warning("[complaint-summary] 요약 실패 — 원문을 쓴다", exc_info=True)
        return None

    # content 는 블록 배열이다 — text 블록만 이어 붙인다
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    summary = " ".join(parts).strip()
    if not summary:
        logger.warning("[complaint-summary] 빈 응답 — 원문을 쓴다")
        return None

    # 모델이 따옴표를 붙여 오는 일이 있다 — 벽에 걸리는 글이라 벗겨 둔다
    summary = summary.strip().strip('"“”「」\'')
    # **끝의 마침표를 뗀다.** 프롬프트로 못 박아도 어떤 줄에만 붙어 오는데,
    # 다섯 줄이 나란히 서는 화면이라 하나만 점이 있으면 눈에 띈다.
    # 물음표·느낌표는 그대로 둔다 — 그건 뜻이 있는 부호다.
    summary = summary.rstrip().rstrip(".。").rstrip()
    logger.info("[complaint-summary] %d자 → %d자", len(clean), len(summary))
    return summary or None


__all__ = ["summarize_complaint", "MIN_LEN"]
