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

    # **회원이 보는 화면의 주소** — 설문 QR·매장 TV·PT 폼 링크에 찍히는 값이다.
    #
    # 2026-08-20 부터 `HiFIS-Client-V2`(Next.js) 가 그리는 곳이다. 그 전에는
    # 이 서버가 HTML 을 직접 내려줘서 `api.hifis.app` 이었다.
    # 매장 벽에 붙고 회원에게 문자로 가는 주소라 `localhost` 가 들어가면 아무도 못 연다.
    public_base_url: str = "https://hifis.app"

    # 계정관리 비번 암호화 마스터 키 (§9.6) — AES-256, 64 hex(32 byte). openssl rand -hex 32
    account_master_key: str = "00" * 32

    # 웹푸시 VAPID (§9.4) — 비면 푸시 발송 스킵(앱 내 알림은 그대로 저장). vapid --gen 으로 발급
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@hifis.local"

    # 앱 푸시 APNs (§9.4) — 셋 다 있어야 보낸다. 비면 스킵(앱 내 알림은 그대로 저장).
    #
    # developer.apple.com → Keys → Apple Push Notifications service 로 .p8 을 받는다.
    # **유료 개발자 계정이 필요하다** — 무료 프로비저닝은 aps-environment 를 못 받는다.
    # apns_private_key 는 .p8 **파일 내용 그대로**(-----BEGIN PRIVATE KEY----- 포함).
    # .env 한 줄에 넣으려면 줄바꿈을 \n 으로 바꿔 적는다.
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_private_key: str = ""
    apns_topic: str = "app.hifis.hifis"  # 번들 ID (네 플랫폼 공통)

    # 앱 푸시 FCM (§9.4) — **안드로이드 전용.** 둘 다 있어야 보낸다.
    #
    # 구글이 다른 길을 안 줘서 안드로이드만 FCM 을 거친다 (애플은 APNs 직접).
    # Firebase 콘솔 → 프로젝트 설정 → 서비스 계정 → 새 비공개 키 생성.
    # fcm_service_account 는 받은 **JSON 파일 내용 그대로**다 —
    # .env 한 줄에 넣어야 하므로 개행 없이 압축해서 적는다
    # (`python3 -c "import json,sys;print(json.dumps(json.load(open(sys.argv[1]))))"`).
    fcm_project_id: str = ""
    fcm_service_account: str = ""

    # 서버 내부 훅 토큰 (§보안) — 사람 계정이 아니라 **서버 자신**이 부르는 자리.
    # 지금은 `POST /security/ssh-login` 하나가 쓴다 (SSH 접속 알림).
    # 비면 그 엔드포인트가 **항상 401** 이다 — 실수로 열려 있는 상태가 안 생긴다.
    internal_hook_token: str = ""

    # 이메일 발송(비밀번호 재설정 인증번호 등, §2.3) — smtp_host 비면 로그 스텁으로 폴백(개발).
    # 무료 SMTP 계정 하나면 충분(예: Gmail/Naver 587 STARTTLS).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""          # 발신 표시 주소(비면 smtp_user 사용)
    smtp_starttls: bool = True

    # 문자(SMS) 발송 — 솔라피. **셋이 다 채워져야** 실제로 나가고, 하나라도 비면 로그 폴백.
    #
    # solapi_sender 는 **솔라피 콘솔에 사전등록·인증이 끝난 번호**여야 한다 (전기통신사업법).
    # 등록 안 된 번호를 넣으면 발송이 통째로 거부된다.
    # HiFIS v1 이 쓰던 계정·발신번호를 그대로 넣으면 된다 (같은 회사·같은 번호).
    solapi_api_key: str = ""
    solapi_api_secret: str = ""
    solapi_sender: str = ""

    #: **대표만 쓸 수 있게 잠근다** — 사고 대응용 임시 스위치 (2026-08-18)
    #:
    #: 켜면 MASTER 가 아닌 사람은 로그인도, 이미 받아 둔 토큰으로 부르는 것도
    #: 전부 `503 LOCKED_DOWN` 이다.
    #:
    #: **끄고 켜는 데 코드 배포가 필요 없다** — `.env` 의 `MASTER_ONLY` 를 바꾸고
    #: 컨테이너를 다시 띄우면 된다 (`.env` 는 뜰 때 한 번만 읽는다).
    #:
    #: **지점 출퇴근 단말은 안 막힌다** — 사람 토큰이 아니라 `X-Terminal-Token`
    #: 으로 들어와서 이 검사를 안 거친다. 잠가 두는 동안에도 카운터에서 출퇴근은
    #: 계속 찍힌다 (그것도 막아야 하면 단말을 폐기한다).
    master_only: bool = False

    # 초기 부트스트랩 시드 (app.seed) — 첫 지점(전사 HQ)·관리자
    seed_branch_name: str = "전 지점"  # HQ 지점명 (§62). 기존 HQ 는 type 으로 찾아 재사용.
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
