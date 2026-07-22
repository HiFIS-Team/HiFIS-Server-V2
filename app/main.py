"""HiFIS FastAPI 진입점 — 앱 생성 · CORS · 라우터 등록 (CLAUDE.md §8)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import branches
from app.core.config import settings
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup / shutdown 훅. 스케줄러 등은 이후 Phase 에서 여기에 연결.
    yield
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

app.include_router(branches.router)


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
