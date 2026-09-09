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


#: 직원이 적은 정비 기록을 **TV 에 걸 한 줄로 다듬는** 프롬프트 (2026-09-09 요청)
#:
#: 컴플레인 요약과 방향이 반대다 — 저기는 길게 쓴 것을 **줄이고**, 여기는
#: `수건 부족` 처럼 짧게 적은 것을 **문장으로 편다.** 그래서 [MIN_LEN] 을 안 본다.
#:
#: **같은 말투로 맞춘다.** 한 화면에 컴플레인 요약과 나란히 서는데 하나는
#: `~해요` 이고 하나는 `수건 부족` 이면 두 벌로 읽힌다.
_SYSTEM_ENV = (
    "너는 헬스장 직원이 남긴 정비 기록을 매장 TV 에 걸 한 줄로 다듬는 일을 한다.\n"
    "회원이 읽는 글이다.\n"
    "\n"
    "규칙\n"
    "- 한국어 한 문장, 공백 포함 35자 이내\n"
    "- **적힌 내용만 쓴다. 없는 말을 지어내지 않는다**\n"
    "- 회원에게 말하듯 부드럽게 (예: '~했어요', '~어요')\n"
    "- 내부에서만 쓰는 말·치수·물건 이름은 쉬운 말로 바꾼다\n"
    "- 따옴표·말줄임표·앞뒤 설명을 붙이지 않는다. 다듬은 문장만 답한다\n"
    "- 사람 이름·연락처는 넣지 않는다\n"
    "- 무슨 일인지 알 수 없거나 뜻이 없는 글이면 **아무것도 답하지 않는다**\n"
    "\n"
    "예시\n"
    "입력: 수건 부족\n"
    "출력: 수건이 부족해서 채워 두었어요\n"
    "입력: 바벨 가운데 1.5mm 종이 테이프 부착완료\n"
    "출력: 바벨 중앙에 표시를 붙였어요\n"
    "입력: 장시간 기구 사용 금지 문구 부착\n"
    "출력: 장시간 기구 사용을 자제해 달라는 안내를 붙였어요\n"
    "입력: 없습니다!!\n"
    "출력:\n"
)


async def summarize_complaint(text: str) -> str | None:
    """컴플레인 한 줄 요약 — **못 만들면 `None`.**

    부르는 쪽은 돌려받은 값이 있을 때만 저장하고, 없으면 원문을 그대로 둔다.
    """
    clean = (text or "").strip()
    # 짧은 것은 안 줄인다 — 회원이 쓴 말 그대로가 낫다
    if not clean or len(clean) <= MIN_LEN:
        return None
    return await _ask(_SYSTEM, clean, tag="complaint-summary")


async def polish_env_note(text: str) -> str | None:
    """직원이 적은 정비 기록을 TV 에 걸 한 줄로 다듬는다 (2026-09-09 요청).

    **길이 문턱이 없다.** `수건 부족` 처럼 짧게 적는 것이 오히려 다듬어야 하는
    자리다 — 줄이는 것이 아니라 문장으로 펴는 일이다.

    못 만들면 `None` 이고, 그러면 **TV 에 안 건다** (컴플레인은 원문으로
    떨어지지만 여기는 원문이 `바벨 중앙 표시목 부착` 이라 벽에 걸 글이 아니다).
    """
    clean = (text or "").strip()
    if not clean:
        return None
    return await _ask(_SYSTEM_ENV, clean, tag="env-summary")


async def _ask(system: str, clean: str, *, tag: str) -> str | None:
    """Claude 에 한 줄을 받아 온다 — **실패는 전부 `None`.**

    부르는 쪽이 곁가지라(요약이 없어도 일은 끝나야 한다) 여기서 예외를 안 낸다.
    """
    if not settings.anthropic_api_key:
        logger.info("[%s] 키가 없어 건너뜀", tag)
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
                    "system": system,
                    "messages": [{"role": "user", "content": clean}],
                },
            )
            res.raise_for_status()
            data = res.json()
    except Exception:
        logger.warning("[%s] 실패 — 부르는 쪽이 원문을 쓴다", tag, exc_info=True)
        return None

    # content 는 블록 배열이다 — text 블록만 이어 붙인다
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    summary = " ".join(parts).strip()
    if not summary:
        logger.info("[%s] 빈 응답 — 다듬을 것이 없다고 봤다", tag)
        return None

    # 모델이 따옴표를 붙여 오는 일이 있다 — 벽에 걸리는 글이라 벗겨 둔다
    summary = summary.strip().strip('"“”「」\'')
    # **끝의 마침표를 뗀다.** 프롬프트로 못 박아도 어떤 줄에만 붙어 오는데,
    # 다섯 줄이 나란히 서는 화면이라 하나만 점이 있으면 눈에 띈다.
    # 물음표·느낌표는 그대로 둔다 — 그건 뜻이 있는 부호다.
    summary = summary.rstrip().rstrip(".。").rstrip()
    logger.info("[%s] %d자 → %d자", tag, len(clean), len(summary))
    return summary or None


__all__ = ["summarize_complaint", "MIN_LEN"]
