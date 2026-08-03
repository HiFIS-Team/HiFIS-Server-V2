"""애플리케이션 설정 — pydantic-settings + .env (CLAUDE.md §8)."""

from pydantic import model_validator
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
    password_reset_token_expire_minutes: int = 10  # 비번 재설정 토큰 유효(분) — verify→confirm 사이
    access_log_retention_days: int = 90  # 접속 로그 보존기간 — 통신비밀보호법 3개월(개인정보처리방침 §3)

    # 외부 웹훅 (네이버폼 등 회원 친절도 설문 수신) 시크릿 (§4.5)
    kindness_webhook_secret: str = "change-me-webhook-secret"

    # 계정관리 비번 암호화 마스터 키 (§9.6) — AES-256, 64 hex(32 byte). openssl rand -hex 32
    account_master_key: str = "00" * 32

    # 웹푸시 VAPID (§9.4) — 비면 푸시 발송 스킵(앱 내 알림은 그대로 저장). vapid --gen 으로 발급
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@hifis.local"

    # 이메일 발송(비밀번호 재설정 인증번호 등, §2.3) — smtp_host 비면 로그 스텁으로 폴백(개발).
    # 무료 SMTP 계정 하나면 충분(예: Gmail/Naver 587 STARTTLS). 문자(SMS)는 후순위.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""          # 발신 표시 주소(비면 smtp_user 사용)
    smtp_starttls: bool = True

    # 초기 부트스트랩 시드 (app.seed) — 첫 지점(전사 HQ)·관리자
    seed_branch_name: str = "전체"  # HQ 지점명 (§62). 기존 HQ 는 type 으로 찾아 재사용.
    seed_admin_name: str = "관리자"
    seed_admin_email: str = "admin@hifis.local"
    seed_admin_password: str = "admin1234"

    # CORS — PWA 오리진만 허용, 콤마 구분 (§9.7)
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _guard_secrets(self) -> "Settings":
        """기동 시 시크릿 검증 — .env 미주입/플레이스홀더면 즉시 실패(fail-closed).

        빈 값이나 알려진 기본값으로는 부팅 금지: 토큰 위조·계정비번 복호화(§C1) 원천 차단.
        """
        insecure = {
            "jwt_secret": "change-me-in-env",
            "account_master_key": "00" * 32,
            "kindness_webhook_secret": "change-me-webhook-secret",
        }
        for field, placeholder in insecure.items():
            value = getattr(self, field)
            if not value or value == placeholder:
                raise ValueError(
                    f"보안 설정 '{field}' 가 비었거나 기본(안전하지 않은) 값입니다 "
                    f"— .env 에 실제 시크릿을 설정하세요"
                )
        if self.environment != "development" and self.seed_admin_password == "admin1234":
            raise ValueError("프로덕션에서 seed_admin_password 기본값(admin1234) 사용 금지")
        return self


settings = Settings()
