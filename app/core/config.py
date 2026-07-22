"""애플리케이션 설정 — pydantic-settings + .env (CLAUDE.md §8)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "HiFIS API"
    environment: str = "development"
    debug: bool = True

    # 인프라 (docker-compose 의 db / redis 서비스) — Phase 진행하며 연결
    database_url: str = "postgresql+asyncpg://hifis:hifis@db:5432/hifis"
    redis_url: str = "redis://redis:6379/0"

    # 보안 — 실제 값은 .env 로 주입 (§9.6, §10 시크릿)
    jwt_secret: str = "change-me-in-env"

    # CORS — PWA 오리진만 허용, 콤마 구분 (§9.7)
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
