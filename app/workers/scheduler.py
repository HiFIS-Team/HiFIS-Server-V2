"""APScheduler 인프로세스 스케줄러 (CLAUDE.md §9.5).

⚠️ 다중 워커(gunicorn)면 워커마다 스케줄러가 떠 잡이 중복 실행됨.
   운영에선 스케줄러 전용 프로세스 1개 또는 Redis 잠금으로 단일화 필요.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.workers.event_reminders import event_reminders
from app.workers.payday_reminder import payday_deadline_reminders, payday_reminders
from app.workers.payroll_close import close_previous_month
from app.workers.project_reminders import project_reminders
from app.workers.ranking_jobs import announce_monthly_winners, ranking_change_scan

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
    # 매일 00:05 UTC(=09:05 KST) — 오늘/내일 지급일 급여 신청 알림(예고 포함)
    scheduler.add_job(
        payday_reminders,
        CronTrigger(hour=0, minute=5),
        id="payday_reminder",
        replace_existing=True,
    )
    # 매일 11:00 UTC(=20:00 KST) — 지급일 당일 미신청자 마감 임박 알림
    scheduler.add_job(
        payday_deadline_reminders,
        CronTrigger(hour=11, minute=0),
        id="payday_deadline",
        replace_existing=True,
    )
    # 매시간 정각 UTC — 프로젝트 마감(전 D-N 매일 9시 / 당일 매시간 / 누락 1회)
    scheduler.add_job(
        project_reminders,
        CronTrigger(minute=0),
        id="project_reminder",
        replace_existing=True,
    )
    # 매일 00:00 UTC(=09:00 KST) — 일정 D-7/D-3/전날/당일 리마인더
    scheduler.add_job(
        event_reminders,
        CronTrigger(hour=0, minute=0),
        id="event_reminder",
        replace_existing=True,
    )
    # 매월 1일 01:00 UTC(=10:00 KST) — 전월 랭킹 1등 발표(급여마감 00:30 이후라 SALES 반영됨)
    scheduler.add_job(
        announce_monthly_winners,
        CronTrigger(day=1, hour=1, minute=0),
        id="ranking_monthly",
        replace_existing=True,
    )
    # 5분마다 — 순위 변동 감지(밀려난 본인 + 어드민 알림)
    scheduler.add_job(
        ranking_change_scan,
        CronTrigger(minute="*/5"),
        id="ranking_change",
        replace_existing=True,
    )
    # TODO(§9.5): 세션 만료 스캔, 점수 기간 롤오버 잡 추가
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
