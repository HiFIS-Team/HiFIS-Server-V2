"""APScheduler 인프로세스 스케줄러 (CLAUDE.md §9.5).

멀티워커(gunicorn --workers N) 안전화: **Redis 리더 락**으로 한 번에 한 워커만
스케줄러를 실행한다. 각 워커는 스케줄러를 paused 로 띄우고, 락을 잡은 '리더'만
resume() 한다. 리더가 죽으면 락 TTL 만료 → 다른 워커가 이어받는다(failover).

Redis 미설정 시엔 리더선출 없이 바로 실행(단일 프로세스 개발 전제).
"""

import asyncio
import logging
import os
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.workers.absence_alerts import absence_alerts
from app.workers.event_reminders import event_reminders
from app.workers.payday_reminder import payday_reminders
from app.workers.payroll_close import close_previous_month
from app.workers.project_reminders import project_reminders
from app.workers.ranking_jobs import (
    announce_monthly_winners,
    board_overtake_scan,
    ranking_change_scan,
)
from app.workers.anomaly_scan import anomaly_scan
from app.workers.error_rate_scan import error_rate_scan
from app.workers.metrics_flush import flush_metrics
from app.workers.my_task_miss_reminders import my_task_miss_reminders
from app.workers.my_task_miss_scan import my_task_miss_scan
from app.workers.peer_review_miss_scan import peer_review_miss_scan
from app.workers.peer_review_reminders import peer_review_reminders
from app.workers.retention import purge_old_access_logs

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")

_LOCK_KEY = "hifis:scheduler:leader"
_TTL_S = 30       # 락 유효기간 — 리더가 죽으면 이 시간 내 만료
_RENEW_S = 10     # 리더 갱신/후보 재시도 주기
_HB_KEY = "hifis:scheduler:hb"  # 하트비트(단일 실행 검증용) — SCHED_HEARTBEAT_TEST 일 때만

_token = uuid.uuid4().hex  # 이 워커의 락 소유 토큰
_redis = None
_campaign_task: asyncio.Task | None = None
_flush_task: asyncio.Task | None = None
_is_leader = False

# get==token 일 때만 연장/삭제(다른 워커 락을 건드리지 않도록 CAS)
_RENEW_LUA = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('pexpire',KEYS[1],ARGV[2]) else return 0 end"
_RELEASE_LUA = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"


async def _heartbeat() -> None:
    """단일 실행 검증용 카운터(운영 기본 비활성). 리더만 도니 워커수와 무관하게 1씩 증가."""
    if _redis is not None:
        await _redis.incr(_HB_KEY)


def _register_jobs() -> None:
    # 매월 1일 00:30 UTC — 전월 급여 마감
    scheduler.add_job(close_previous_month, CronTrigger(day=1, hour=0, minute=30),
                      id="payroll_close", replace_existing=True)
    # 매일 00:05 UTC(=09:05 KST) — 오늘/내일 지급일 급여 신청 알림(예고 포함)
    # KST 09·12·15·18·21시 (= UTC 00·03·06·09·12) — 지급일 전날 6시간마다,
    # 당일은 안 낸 사람에게 3시간마다. 새벽은 뺀다 (payday_reminder.py)
    scheduler.add_job(payday_reminders, CronTrigger(hour="0,3,6,9,12", minute=5),
                      id="payday_reminder", replace_existing=True)
    # 매일 11:00 UTC(=20:00 KST) — 지급일 당일 미신청자 마감 임박 알림
    # 매시간 정각 UTC — 프로젝트 마감(전 D-N 매일 9시 / 당일 매시간 / 누락 1회)
    scheduler.add_job(project_reminders, CronTrigger(minute=0),
                      id="project_reminder", replace_existing=True)
    # 매시간 정각 — 결근 알림(대표·관리자). 사람마다 퇴근 시간이 달라서
    # **본인 퇴근 시간이 막 지난 그 정각**에만 한 번 나간다 (absence_alerts 주석 참고)
    scheduler.add_job(absence_alerts, CronTrigger(minute=0),
                      id="absence_alert", replace_existing=True)
    # 매일 00:00 UTC(=09:00 KST) — 일정 D-7/D-3/전날/당일 리마인더
    scheduler.add_job(event_reminders, CronTrigger(hour=0, minute=0),
                      id="event_reminder", replace_existing=True)
    # 매월 1일 01:00 UTC(=10:00 KST) — 전월 랭킹 1등 발표(급여마감 00:30 이후라 SALES 반영됨)
    scheduler.add_job(announce_monthly_winners, CronTrigger(day=1, hour=1, minute=0),
                      id="ranking_monthly", replace_existing=True)
    # 5분마다 — 순위 변동 감지(밀려난 본인 + 어드민 알림)
    scheduler.add_job(ranking_change_scan, CronTrigger(minute="*/5"),
                      id="ranking_change", replace_existing=True)
    # 5분마다 — 랭킹판(매출·친절·…) 추월 기록. 위 잡과 보는 값이 달라 따로 돈다
    # (저쪽은 점수 원장, 이쪽은 앱 랭킹 화면이 그리는 판). 알림은 저쪽만 보낸다.
    scheduler.add_job(board_overtake_scan, CronTrigger(minute="*/5"),
                      id="board_overtake", replace_existing=True)
    # 매일 15:30 UTC(=00:30 KST) — 개인 업무 확정 누락 판정.
    # **어제가 다 끝난 뒤여야** 한다 — 어제 밀려 온 것을 어제 안에 체크했는지를
    # 보기 때문이다. 자정 직후가 그 첫 자리다.
    scheduler.add_job(my_task_miss_scan, CronTrigger(hour=15, minute=30),
                      id="my_task_miss_scan", replace_existing=True)
    # 매시 정각 — 개인 업무 누락 재촉 푸시(**본인에게만**). 시간대를 안 자른다:
    # 누락은 퇴근한 뒤에 나는 일이라 밤을 빼면 저녁에 한두 번 울리고 끝난다
    # (2026-08-31 대표 결정 — "확정 전까지는 1시간마다 그냥").
    # 쉬는 날은 목록이 비어서 저절로 조용하다.
    scheduler.add_job(my_task_miss_reminders, CronTrigger(minute=0),
                      id="my_task_miss_reminder", replace_existing=True)
    # 매시 정각 UTC 00~14 (=KST 09~23) — 동료평가 재촉 푸시.
    # **잡 안에서 창(말일·1일)인지 다시 본다** — 크론은 시각만 자른다.
    scheduler.add_job(peer_review_reminders, CronTrigger(hour="0-14", minute=0),
                      id="peer_review_reminder", replace_existing=True)
    # 매일 15:30 UTC(=00:30 KST) — 동료평가 미제출 감점.
    # **창이 닫힌 다음 날(2일)에만** 실제로 돈다 (잡이 어제가 1일인지 본다).
    # 개인 업무 누락 판정과 같은 시각이다 — 하루가 다 끝난 뒤가 첫 자리다.
    scheduler.add_job(peer_review_miss_scan, CronTrigger(hour=15, minute=30),
                      id="peer_review_miss_scan", replace_existing=True)
    # 매일 02:00 UTC — 보존기간(기본 90일) 초과 접속 로그 파기(§3 통신비밀보호법)
    scheduler.add_job(purge_old_access_logs, CronTrigger(hour=2, minute=0),
                      id="access_log_purge", replace_existing=True)
    # 5분마다 — 이상행동 감지(로그인 반복 실패·권한 없는 요청·새 기기·대량 삭제/열람)
    scheduler.add_job(anomaly_scan, CronTrigger(minute="*/5"),
                      id="anomaly_scan", replace_existing=True)
    # 5분마다 — 5xx 급증 감지(개발자에게). 위 잡과 달리 사람이 아니라 **서버**를 본다
    scheduler.add_job(error_rate_scan, CronTrigger(minute="*/5"),
                      id="error_rate_scan", replace_existing=True)
    # 15분마다 — 출퇴근 단말 침묵 감지(대표에게).
    # **아침에 잡아야 뜻이 있다** — 저녁 결근 알림이 나가기 전에 고쳐야
    # 그날 나온 사람이 결근으로 안 남는다. 하루 한 번만 알린다(alerted_at).
    # 검증용 하트비트 — 환경변수로만 켬(운영 기본 꺼짐). 멀티워커 단일실행 확인에 사용.
    if os.getenv("SCHED_HEARTBEAT_TEST"):
        scheduler.add_job(_heartbeat, CronTrigger(second="*/2"),
                          id="heartbeat_test", replace_existing=True)
    # TODO(§9.5): 세션 만료 스캔, 점수 기간 롤오버 잡 추가


async def _flush_loop() -> None:
    """응답 지표 내려쓰기 — **리더와 무관하게 모든 워커가 돈다.**

    버퍼는 워커 메모리에 따로 쌓인다. 스케줄러 잡으로 넣으면 리더 한 대만
    내려써서 나머지 워커가 받은 요청이 통째로 사라진다.
    """
    while True:
        try:
            await asyncio.sleep(60)
            await flush_metrics()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("scheduler: 응답 지표 기록 실패", exc_info=True)


async def start_scheduler(redis_url: str | None) -> None:
    """스케줄러 기동. Redis 있으면 리더 락으로 단일 워커만 실행, 없으면 바로 실행."""
    global _redis, _campaign_task, _flush_task
    if scheduler.running:
        return
    _register_jobs()
    _flush_task = asyncio.create_task(_flush_loop())

    if not redis_url:
        scheduler.start()  # 단일 프로세스 — 바로 실행
        logger.info("scheduler: 로컬 모드(단일 프로세스)로 시작")
        return

    scheduler.start(paused=True)  # 리더가 되기 전엔 잡 미발화
    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        await _redis.ping()
    except Exception:
        # Redis 불가 시엔 '실행 안 함'이 안전(중복 급여마감보다 미발화가 낫다). 복구되면 리더 획득.
        logger.warning("scheduler: Redis 불가 → 대기(잡 미발화), 복구 시 리더 선출", exc_info=True)
        _redis = None
    _campaign_task = asyncio.create_task(_campaign())


async def _campaign() -> None:
    """리더 선출 루프 — 락을 잡으면 resume, 잃으면 pause."""
    global _is_leader
    while True:
        try:
            if _redis is not None:
                if _is_leader:
                    renewed = await _redis.eval(_RENEW_LUA, 1, _LOCK_KEY, _token, str(_TTL_S * 1000))
                    if not renewed:  # 락 잃음(예: 일시 정지·네트워크) → 안전하게 멈춤
                        _is_leader = False
                        scheduler.pause()
                        logger.warning("scheduler: 리더십 상실 → 일시정지")
                if not _is_leader:
                    got = await _redis.set(_LOCK_KEY, _token, nx=True, ex=_TTL_S)
                    if got:
                        _is_leader = True
                        scheduler.resume()
                        logger.info("scheduler: 리더 획득 → 스케줄러 실행(이 워커만 잡 발화)")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("scheduler: 리더선출 루프 오류", exc_info=True)
        await asyncio.sleep(_RENEW_S)


async def stop_scheduler() -> None:
    global _campaign_task, _flush_task
    if _flush_task is not None:
        _flush_task.cancel()
        _flush_task = None
        # 마지막 1분치를 흘리지 않는다
        try:
            await flush_metrics()
        except Exception:
            logger.warning("scheduler: 종료 시 응답 지표 기록 실패", exc_info=True)
    if _campaign_task is not None:
        _campaign_task.cancel()
        try:
            await _campaign_task
        except Exception:
            pass
        _campaign_task = None
    if scheduler.running:
        scheduler.shutdown(wait=False)
    if _redis is not None:
        if _is_leader:  # 내 락이면 즉시 해제 → 다른 워커가 바로 이어받음
            try:
                await _redis.eval(_RELEASE_LUA, 1, _LOCK_KEY, _token)
            except Exception:
                pass
        try:
            await _redis.aclose()
        except Exception:
            pass
