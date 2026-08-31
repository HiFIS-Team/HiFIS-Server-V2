FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# 의존성 설치 (pyproject 기준). setuptools 빌드에 앱 소스가 필요해 함께 복사.
# **alembic 도 같이 굽는다** — 아래 CMD 가 뜰 때 마이그레이션을 돌린다.
# 안 넣으면 컨테이너가 시작조차 못 한다 (main 은 `COPY . .` 로 통째로 구워서
# 우연히 들어가 있었다 — 2026-08-12 에 두 브랜치를 맞추면서 명시로 바꿨다).
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY alembic ./alembic
RUN pip install .

EXPOSE 8000

# 프로덕션 기본 실행 (§8: gunicorn + uvicorn worker).
# 개발은 docker-compose 가 uvicorn --reload 로 command 를 override.
#
# **마이그레이션을 먼저 돌린다.** 이 줄은 원래 main 브랜치에만 있었고 develop 에는
# 없었다 (2026-08-12 발견). 배포는 main 을 보므로 지금 도는 서버는 이 모양인데,
# develop 에서 이 자리를 건드리면 머지에서 충돌하거나 조용히 사라진다.
# 사라져도 배포 스크립트가 alembic 을 따로 돌려서 **한동안 티가 안 난다** — 그게 더 나쁘다.
# 그래서 두 브랜치를 같은 내용으로 맞춰 둔다.
#
# **`head` 가 아니라 `heads` 다.** 이 레포는 갈래가 여럿이라 헤드도 여럿인데,
# `upgrade head` 는 그때 DB 상태와 상관없이 **무조건 죽는다**
# (`Multiple head revisions are present`). 죽으면 gunicorn 이 안 떠서
# 컨테이너가 재시작만 돈다 — 2026-08-31 운영이 실제로 그렇게 내려갔다.
# 사람이 손으로 돌릴 때도 `alembic upgrade heads` 다 (CLAUDE.md).
#
# 워커 수는 `.env` 의 `GUNICORN_WORKERS` 로 바꾼다 (기본 4).
# 예전에는 2로 박혀 있었는데 서버 코어가 8개라 놀리는 자원이 많았다.
# **재빌드 없이** 바꾸려고 환경변수로 뺐다 — `sh -c` 라 여기서 풀린다.
CMD ["sh", "-c", "alembic upgrade heads && gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-4} --access-logfile -"]
