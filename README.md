# HiFIS-Server-V2

[ HiFIS-V2 ㅣ Server ] 피트니스스타 직원 관리 플랫폼 백엔드

**FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL 16** — 홈서버 self-host 구성.
도메인 모델·API 계약은 프론트(`HiFIS-Client-V2`)와 공유하는 설계 문서 기준으로 구현한다.

## 기술 스택

| 구분 | 사용 |
|------|------|
| 런타임 | Python 3.12+ |
| 웹 | FastAPI · Uvicorn · Gunicorn |
| DB | PostgreSQL 16 · SQLAlchemy 2.0 (async) · Alembic |
| 검증 | Pydantic v2 · pydantic-settings |
| 인증 | OAuth2 + JWT (python-jose) · passlib[bcrypt] |
| 캐시/실시간 | Redis |
| 배포 | Docker Compose · Caddy (자동 HTTPS) |

## 요구 사항

- [Docker](https://docs.docker.com/get-docker/) & Docker Compose
- (도커 없이 로컬 실행 시) Python 3.12+

## 빠른 시작 (Docker)

```bash
# 1. 환경 변수 준비 (없으면 예시에서 복사)
cp .env.example .env      # 이미 있으면 생략. JWT_SECRET·비밀번호 확인/교체

# 2. 빌드 & 실행 (db + redis + api)
docker compose up -d --build

# 3. DB 마이그레이션 적용
docker compose exec api alembic upgrade head

# 4. 초기 관리자·지점 시드 (.env 의 SEED_* 값 사용)
docker compose exec api python -m app.seed
```

기본 관리자: `admin@hifis.local` / `admin1234` (운영 전 반드시 교체). 로그인은 `POST /auth/login`.

- API: http://localhost:8001
- 헬스체크: http://localhost:8001/health
- API 문서(Swagger): http://localhost:8001/docs

개발 모드에선 `./app`이 컨테이너에 마운트돼 **코드 저장 시 자동 리로드**된다.

> 호스트 포트는 api `8001` / db `5434` / redis `6380` 을 쓴다 (이 서버에서 `8000·5432·6379`는 다른 스택이 사용 중이라 충돌 회피). 컨테이너 내부 포트는 그대로라 `.env`의 `DATABASE_URL`·`REDIS_URL`은 수정 불필요.

### 운영 배포 (Caddy 자동 HTTPS)

```bash
# .env 에 DOMAIN=your-subdomain.example.com 지정 후
docker compose --profile prod up -d --build
```

> ⚠️ 기존 `cloudflared` / `hifis.app` 설정은 건드리지 말 것. 새 서브도메인을 `DOMAIN`으로 사용한다.

## 로컬 실행 (도커 없이)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

별도 PostgreSQL·Redis가 필요하며 `.env`의 `DATABASE_URL`·`REDIS_URL`을 로컬 주소로 맞춘다.

## 환경 변수

| 키 | 설명 | 예시 |
|----|------|------|
| `DATABASE_URL` | async DB 접속 URL | `postgresql+asyncpg://hifis:...@db:5432/hifis` |
| `REDIS_URL` | Redis 접속 URL | `redis://redis:6379/0` |
| `JWT_SECRET` | JWT 서명 시크릿 (긴 랜덤값) | `openssl rand -hex 32` |
| `CORS_ORIGINS` | 허용 프론트 오리진 (콤마 구분) | `http://localhost:3000` |
| `DOMAIN` | Caddy 배포 도메인 (미설정 시 localhost) | `hifis-api.example.com` |

`.env`는 gitignore 처리되어 커밋되지 않는다. 운영에선 파일 권한 600 권장.

## 브랜치 전략

- `main` — 배포/안정 브랜치
- `develop` — 통합 개발 브랜치 (기능은 여기서 병합)

## 프로젝트 구조

```
app/
  main.py          # FastAPI 앱 · 라우터 등록 · CORS
  core/
    config.py      # pydantic-settings 설정
Dockerfile
docker-compose.yml # db · redis · api · caddy(prod)
Caddyfile          # 리버스 프록시 + 자동 HTTPS
pyproject.toml
```

> 도메인 모듈(models / schemas / api / services …)은 Phase 진행하며 추가한다.
