"""활동 로그 미들웨어 — 쓰기 요청이 지나갈 때 한 줄씩 적는다.

**라우트를 하나도 안 고친다.** 앱이 이미 보내고 있는 요청을 받아 적기만 하므로
새 엔드포인트가 생겨도 자동으로 남는다 (한국어 라벨만 `services/audit.py` 에 더한다).

기록에 실패해도 요청은 그대로 성공시킨다 — 로그 때문에 앱이 멈추면 안 된다.
"""

import json
import logging
from urllib.parse import unquote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.ratelimit import client_key
from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.platform.audit_log import AuditLog
from app.services.audit import NO_PAYLOAD, READ_LOGGED, SKIP, mask, normalize

logger = logging.getLogger(__name__)

# 남기는 메서드 — GET 은 원칙적으로 안 남긴다(조회는 하루 수만 건이고 '한 일'이 아니다).
# 예외는 READ_LOGGED — 남의 기록·대화를 열어 본 것만 따로 남긴다
_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})

# 본문 상한 — 공지·회의록 본문은 통째로 남겨야 뜻이 있어서 넉넉히 잡는다
_MAX_BODY = 20_000


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        route = normalize(request.url.path)
        reading = (request.method, route) in READ_LOGGED
        if not reading and request.method not in _METHODS:
            return await call_next(request)
        if (request.method, route) in SKIP:
            return await call_next(request)

        # 열람은 본문이 없다 — 대신 '무슨 조건으로 찾았나'가 쿼리에 있다.
        # 퍼센트 인코딩을 풀어야 화면에서 `q=저녁` 으로 읽힌다
        payload = (
            {"_query": unquote(request.url.query)[:500]} if request.url.query else None
        ) if reading else await self._payload(request, route)
        response = await call_next(request)

        try:
            await self._write(request, route, response.status_code, payload)
        except Exception:  # 로그 실패가 요청을 망치면 안 된다
            logger.exception("활동 로그 기록 실패: %s %s", request.method, request.url.path)
        return response

    async def _payload(self, request: Request, route: str) -> dict | None:
        """보낸 내용을 읽어 둔다 — **읽은 스트림은 다시 흘려 줘야** 라우트가 받는다.

        본문을 안 담기로 한 주소여도 스트림은 똑같이 읽고 되돌린다.
        중간에 빠져나가면 뒤에 있는 `body()` 호출과 엇갈린다.
        """
        content_type = request.headers.get("content-type") or ""
        if content_type.startswith("multipart/"):
            return {"_note": "파일 업로드라 본문은 안 남겨요"}

        body = await request.body()

        # body() 는 스트림을 소진한다. 같은 바이트를 다시 내주는 receive 로 갈아끼워
        # 라우트가 정상적으로 본문을 파싱하게 한다.
        async def replay():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = replay  # noqa: SLF001 — Starlette 가 열어 둔 유일한 길

        if (request.method, route) in NO_PAYLOAD:
            return {"_note": "대화 내용은 사내톡 열람에서 봐요"}
        if not body:
            return None
        if len(body) > _MAX_BODY:
            return {"_note": f"본문이 커서 안 남겨요 ({len(body):,}바이트)"}
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return {"_note": "JSON 이 아니라 안 남겨요"}
        masked = mask(parsed)
        # 최상위가 배열·문자열일 수도 있어 JSONB 컬럼에 맞게 감싼다
        return masked if isinstance(masked, dict) else {"_body": masked}

    async def _write(self, request: Request, route: str, status: int, payload: dict | None) -> None:
        # 요청이 쓰던 세션은 이미 닫혔다 — 따로 열어야 로그가 요청 트랜잭션에 안 묶인다
        async with SessionLocal() as db:
            db.add(
                AuditLog(
                    employee_id=await self._employee_id(request, db),
                    method=request.method,
                    path=request.url.path[:500],
                    route=route[:200],
                    status=status,
                    payload=payload,
                    ip=client_key(request),
                    user_agent=(request.headers.get("user-agent") or "")[:300] or None,
                )
            )
            await db.commit()

    async def _employee_id(self, request: Request, db) -> str | None:
        """토큰에서 바로 꺼낸다 — 라우트의 의존성을 안 건드리려고 직접 푼다.

        서명만 확인하므로 폐기된 세션도 id 가 잡히는데, 그 요청은 401 로 남아서
        오히려 '누가 만료된 토큰으로 두드렸나'가 보인다.
        """
        header = request.headers.get("authorization") or ""
        if not header.lower().startswith("bearer "):
            return None
        try:
            employee_id = decode_token(header[7:], expected_type="access").get("sub")
        except Exception:
            return None
        if not employee_id:
            return None
        # 외래키라 없는 id 를 넣으면 통째로 실패한다 — 가입 직후 등 드문 경우를 막는다
        from app.models.staff.employee import Employee

        return employee_id if await db.get(Employee, employee_id) else None
