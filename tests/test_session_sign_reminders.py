"""세션 싸인 재촉 — 30분 뒤 첫 푸시, 그 뒤 1시간마다 한 번씩."""

from datetime import datetime, timedelta, timezone

from app.workers.session_sign_reminders import is_due

WROTE = datetime(2026, 10, 15, 1, 2, 17, tzinfo=timezone.utc)  # 아무 초에나 쓴다


def _ticks(hours: int):
    """5분 정각마다 도는 잡의 시각들"""
    t = WROTE.replace(minute=0, second=0)
    while t < WROTE + timedelta(hours=hours):
        yield t
        t += timedelta(minutes=5)


def test_first_push_after_30_minutes():
    assert not is_due(WROTE, WROTE + timedelta(minutes=29))
    first = next(t for t in _ticks(3) if is_due(WROTE, t))
    assert timedelta(minutes=30) <= first - WROTE < timedelta(minutes=35)


def test_once_per_hour():
    fired = [t for t in _ticks(5) if is_due(WROTE, t)]
    assert len(fired) == 5  # 30분 · 1:30 · 2:30 · 3:30 · 4:30
    assert all(b - a == timedelta(hours=1) for a, b in zip(fired, fired[1:]))
