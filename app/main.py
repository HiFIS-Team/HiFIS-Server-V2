"""HiFIS FastAPI 진입점 — 앱 생성 · CORS · 라우터 등록 (CLAUDE.md §8)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import (
    accounts,
    approvals,
    attendance,
    auth,
    branches,
    contributions,
    dashboard,
    documents,
    employees,
    env,
    events,
    invite_keys,
    join_requests,
    kindness,
    meetings,
    members,
    notices,
    payslips,
    peer_reviews,
    projects,
    rank_policies,
    reactions,
    registrations,
    scores,
    search,
    session_signs,
    todos,
)
from app.core.config import settings
from app.db.session import engine
from app.workers.scheduler import start_scheduler, stop_scheduler


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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(branches.router)
app.include_router(invite_keys.router)
app.include_router(join_requests.router)
app.include_router(members.router)
app.include_router(registrations.router)
app.include_router(session_signs.router)
app.include_router(scores.router)
app.include_router(env.router)
app.include_router(peer_reviews.router)
app.include_router(contributions.router)
app.include_router(kindness.router)
app.include_router(rank_policies.router)
app.include_router(payslips.router)
app.include_router(projects.router)
app.include_router(todos.router)
app.include_router(notices.router)
app.include_router(meetings.router)
app.include_router(events.router)
app.include_router(attendance.router)
app.include_router(approvals.router)
app.include_router(accounts.router)
app.include_router(documents.router)
app.include_router(reactions.router)
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
