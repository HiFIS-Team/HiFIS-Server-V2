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
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    # 외부 웹훅 (네이버폼 등 회원 친절도 설문 수신) 시크릿 (§4.5)
    kindness_webhook_secret: str = "change-me-webhook-secret"

    # 계정관리 비번 암호화 마스터 키 (§9.6) — AES-256, 64 hex(32 byte). openssl rand -hex 32
    account_master_key: str = "00" * 32

    # 웹푸시 VAPID (§9.4) — 비면 푸시 발송 스킵(앱 내 알림은 그대로 저장). vapid --gen 으로 발급
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@hifis.local"

    # 초기 부트스트랩 시드 (app.seed) — 첫 지점·관리자
    seed_branch_name: str = "본사"
    seed_admin_name: str = "관리자"
    seed_admin_email: str = "admin@hifis.local"
    seed_admin_password: str = "admin1234"

    # CORS — PWA 오리진만 허용, 콤마 구분 (§9.7)
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
