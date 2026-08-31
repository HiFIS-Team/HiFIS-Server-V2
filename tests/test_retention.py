"""보존기간 — **화면이 요구하는 기간과 파기 잡이 지우는 기간이 어긋나면 안 된다.**

둘이 벌어져도 아무 데서도 에러가 안 난다. 사용자는 **빈 목록**을 받고,
왜 비었는지 알 방법이 없다 (지워진 것인지 원래 없는 것인지 화면이 구분 못 한다).
그런 종류라 여기서 못 박는다.
"""

import inspect

from app.api.chat.notifications import NOTIFICATION_DAYS, list_notifications
from app.core.config import settings


def _max_days(handler, param: str) -> int:
    """그 엔드포인트가 받는 기간 상한.

    **앱(`app.main`)을 안 띄운다** — 함수 시그니처의 `Query(...)` 에서 바로 읽는다.
    라우터를 붙이는 방식이 바뀌어도 이 테스트는 그대로 돈다.
    """
    query = inspect.signature(handler).parameters[param].default
    for rule in query.metadata:
        if hasattr(rule, "le"):
            return rule.le
    raise AssertionError(f"{handler.__name__}({param}) 에 상한이 없다")


def test_알림_조회_상한이_보존기간을_안_넘는다():
    """상한이 더 길면 **파기 잡이 이미 지운 것**을 달라고 하게 된다."""
    assert _max_days(list_notifications, "days") <= settings.access_log_retention_days


def test_알림_기본_기간은_상한_안쪽이다():
    assert NOTIFICATION_DAYS <= settings.access_log_retention_days


def test_파기_잡이_점수_원장을_안_건드린다():
    """`score_events`·`env_task_logs` 는 **점수 근거**다. 지우면 지난 달 랭킹을
    다시 못 뽑는다 — 자라는 것은 인덱스로 풀 문제지 지워서 풀 문제가 아니다."""
    import inspect

    from app.workers import retention

    source = inspect.getsource(retention)
    assert "ScoreEvent" not in source, "점수 원장이 파기 대상에 들어갔다"
    assert "EnvTaskLog" not in source, "환경정비 기록이 파기 대상에 들어갔다"


def test_파기_대상이_여섯이다():
    """하나가 조용히 빠지면 그 테이블만 끝없이 자란다."""
    import inspect

    from app.workers import retention

    source = inspect.getsource(retention.purge_old_access_logs)
    for model in ("AccessLog", "AuditLog", "ApiMetric", "Anomaly", "AppTrail", "Notification"):
        assert f"delete({model})" in source, f"{model} 이 파기 대상에서 빠졌다"
