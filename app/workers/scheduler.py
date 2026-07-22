"""APScheduler 인프로세스 스케줄러 (CLAUDE.md §9.5).

⚠️ 다중 워커(gunicorn)면 워커마다 스케줄러가 떠 잡이 중복 실행됨.
   운영에선 스케줄러 전용 프로세스 1개 또는 Redis 잠금으로 단일화 필요.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.workers.payroll_close import close_previous_month

scheduler = AsyncIOScheduler(timezone="UTC")


def start_scheduler() -> None:
    if scheduler.running:
        return
    # 매월 1일 00:30 UTC — 전월 급여 마감
    scheduler.add_job(
        close_previous_month,
        CronTrigger(day=1, hour=0, minute=30),
        id="payroll_close",
        replace_existing=True,
    )
    # TODO(§9.5): 프로젝트 마감 알림, 세션 만료 스캔, 점수 기간 롤오버 잡 추가
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
