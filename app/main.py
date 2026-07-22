"""HiFIS FastAPI 진입점 — 앱 생성 · CORS · 헬스체크 (CLAUDE.md §8).

도메인 라우터(auth, employees, members, scores ...)는 Phase 1 부터 이 파일에
`app.include_router(...)` 로 등록한다.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup / shutdown 훅. DB 엔진·스케줄러 연결은 이후 Phase 에서 여기에 연결.
    yield


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


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "version": app.version, "docs": "/docs"}
