FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# 의존성 설치 (pyproject 기준). setuptools 빌드에 앱 소스가 필요해 함께 복사.
COPY pyproject.toml ./
COPY app ./app
RUN pip install .

EXPOSE 8000

# 프로덕션 기본 실행 (§8: gunicorn + uvicorn worker).
# 개발은 docker-compose 가 uvicorn --reload 로 command 를 override.
CMD ["gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-b", "0.0.0.0:8000", \
     "--workers", "2", \
     "--access-logfile", "-"]
