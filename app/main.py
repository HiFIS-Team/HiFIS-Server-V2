"""HiFIS FastAPI 진입점 — 앱 생성 · CORS · 라우터 등록 (CLAUDE.md §8)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.collab import (
    approvals,
    chat,
    events,
    meetings,
    notices,
    notifications,
    projects,
    reactions,
    todos,
)
from app.api.org import attendance, auth, branches, employees, invite_keys, join_requests
from app.api.payroll import payslips, rank_policies
from app.api.platform import accounts, dashboard, documents, search
from app.api.sales import members, registrations, session_signs
from app.api.scoring import contributions, env, kindness, peer_reviews, scores
from app.core.config import settings
from app.db.session import engine
from app.workers.scheduler import start_scheduler, stop_scheduler
from app.ws.chat import router as ws_chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()  # 월마감 등 백그라운드 잡 (§9.5)
    yield
    stop_scheduler()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    # LAN(폰) 접속 — 사설망 IP:포트는 정규식으로 허용(DHCP로 IP가 바뀌어도 동작)
    allow_origin_regex=(
        r"^http://(localhost|127\.0\.0\.1"
        r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?$"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# org — 조직·인사
app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(branches.router)
app.include_router(invite_keys.router)
app.include_router(join_requests.router)
app.include_router(attendance.router)
# sales — 회원·매출
app.include_router(members.router)
app.include_router(registrations.router)
app.include_router(session_signs.router)
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
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(dashboard.router)

# 로컬 업로드 정적 서빙 (§9.2). TODO: 서명 등 비공개 파일은 권한 게이트 서빙으로 교체.
app.mount("/uploads", StaticFiles(directory="uploads", check_dir=False), name="uploads")


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
