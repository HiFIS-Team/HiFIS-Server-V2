"""HiFIS FastAPI 진입점 — 앱 생성 · CORS · 라우터 등록 (CLAUDE.md §8)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.core.ratelimit import limiter

from app.api.auth import auth, invite_keys, scan_terminals
from app.api.board import approvals, events, notices, reactions
from app.api.chat import chat, notifications
from app.api.legal import consents
from app.api.members import members, registrations, session_signs
from app.api.payroll import payslips, rank_policies
from app.api.platform import (
    access_logs,
    accounts,
    audit_logs,
    monitoring,
    chat_audit,
    dashboard,
    documents,
    files,
    search,
)
from app.api.projects import meetings, projects, todos
from app.api.public import (
    legal as public_legal,
    survey as public_survey,
    tv as public_tv,
)
from app.api.scoring import contributions, env, kindness, peer_reviews, scores
from app.api.staff import attendance, branches, employees, home
from app.core.audit_middleware import AuditMiddleware
from app.core.metrics_middleware import MetricsMiddleware
from app.core.config import settings
from app.db.session import engine
from app.workers.scheduler import start_scheduler, stop_scheduler
from app.ws.chat import router as ws_chat_router
from app.ws.manager import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await manager.start(settings.redis_url)  # 사내톡 WS Redis 팬아웃(§9.3) — 워커 수 무관 실시간
    await start_scheduler(settings.redis_url)  # 백그라운드 잡 — Redis 리더 락으로 단일 워커만 실행(§9.5)
    yield
    await stop_scheduler()
    await manager.stop()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.7.0",
    lifespan=lifespan,
)

# 레이트리밋(§9.7) — 라우트의 @limiter.limit 데코레이터가 app.state.limiter 를 사용
app.state.limiter = limiter


async def _rate_limit_handler(request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": {"code": "RATE_LIMITED", "message": "요청이 너무 많아요. 잠시 후 다시 시도해주세요"}},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

_cors_kwargs: dict = {
    "allow_origins": settings.cors_origins_list,
    "allow_credentials": True,
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}
# LAN(폰) 접속용 사설망 IP 정규식은 **개발에서만** 허용(DHCP로 IP가 바뀌어도 동작).
# 프로덕션은 자격증명 탈취 방지를 위해 CORS_ORIGINS(.env) 명시 오리진만 허용(§M6).
if settings.environment == "development":
    _cors_kwargs["allow_origin_regex"] = (
        r"^http://(localhost|127\.0\.0\.1"
        r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?$"
    )
app.add_middleware(CORSMiddleware, **_cors_kwargs)
# 활동 로그 — 쓰기 요청을 받아 적는다(§8). CORS 다음에 등록해 프리플라이트(OPTIONS)는 안 탄다
app.add_middleware(AuditMiddleware)
# 응답 시간 계측 — 활동 로그보다 바깥이라 로그 기록 시간까지 포함해 잰다
app.add_middleware(MetricsMiddleware)

# org — 조직·인사
app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(home.router)  # GET /me/home (개인 홈 요약)
app.include_router(branches.router)
app.include_router(invite_keys.router)
app.include_router(scan_terminals.router)  # 지점 출퇴근 단말 토큰 (MASTER)
app.include_router(attendance.router)
# sales — 회원·매출
app.include_router(members.router)
app.include_router(registrations.router)
app.include_router(session_signs.router)
app.include_router(consents.router)  # 법·동의 — 직원 약관(§12)·회원 개인정보(§13)
# scoring — 점수
app.include_router(scores.router)
app.include_router(env.router)
app.include_router(peer_reviews.router)
app.include_router(contributions.router)
app.include_router(kindness.router)
# payroll — 급여
app.include_router(rank_policies.router)
app.include_router(payslips.router)
# collab — 협업
app.include_router(projects.router)
app.include_router(todos.router)
app.include_router(notices.router)
app.include_router(meetings.router)
app.include_router(events.router)
app.include_router(approvals.router)
app.include_router(reactions.router)
app.include_router(notifications.router)
app.include_router(chat.router)
app.include_router(ws_chat_router)  # WS /ws/chat
# platform — 문서·계정·검색·대시보드
app.include_router(accounts.router)
app.include_router(access_logs.router)
app.include_router(audit_logs.router)
app.include_router(monitoring.router)  # 성능 지표·이상행동 감지
app.include_router(chat_audit.router)  # 사내톡 열람(관리자 이상)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(public_survey.router)  # 회원 설문 — **로그인 없음**(매장 QR)
app.include_router(public_tv.router)      # 매장 TV — **로그인 없음**(해결된 컴플레인)
app.include_router(public_legal.router)   # 약관·개인정보처리방침 — **로그인 없음**(스토어 심사용 공개 URL)
app.include_router(dashboard.router)
app.include_router(files.router)  # 서명 URL 파일 서빙(/files) — 정적 /uploads 공개 대체(§H2)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "down"
    return {"status": "ok", "db": db_status}


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "version": app.version, "docs": "/docs"}
