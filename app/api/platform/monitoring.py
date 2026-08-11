"""성능 지표·이상행동 조회 — 모니터링 화면 (개인정보처리방침 §8).

**MASTER 전용이다.** 접속·활동 로그·사내톡 열람과 같은 기준으로,
남의 활동과 대화를 들여다보는 자리라 대표 한 사람만 연다 (ADMIN 도 403).
전 지점 보안 데이터이므로 지점 스코프는 적용하지 않는다.

단 아래의 `POST /security/capture` 는 예외다 — 앱이 '화면이 찍혔다'고
알려 오는 자리라 **전 직원이 부른다.**
"""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import EmployeeStatus, Rank, Role
from app.models.platform.anomaly import Anomaly
from app.models.platform.api_metric import BUCKET_BOUNDS, ApiMetric
from app.models.staff.employee import Employee
from app.schemas.platform.monitoring import (
    AnomalyOut,
    ApiMetricsOut,
    CaptureReport,
    MetricPointOut,
    SlowRouteOut,
    SshLoginReport,
)
from app.services.notifications import notify

router = APIRouter(tags=["monitoring"])

# 버킷 칸 이름 — 경계 순서와 같아야 한다
_BUCKETS = tuple(f"b{bound}" for bound in BUCKET_BOUNDS)


def _percentile(counts: list[int], total: int, ratio: float, max_ms: int) -> int:
    """버킷 히스토그램에서 백분위를 뽑는다 (Prometheus `histogram_quantile` 과 같은 방식).

    칸 안에서는 고르게 퍼져 있다고 보고 선형 보간한다. 그래서 **근사치**다 —
    경계를 촘촘히 둘수록 정확해지고, 마지막 칸(경계 초과)에 걸리면 최대값을 쓴다.
    """
    if total <= 0:
        return 0
    target = total * ratio
    seen = 0
    low = 0
    for bound, count in zip(BUCKET_BOUNDS, counts):
        if seen + count >= target and count > 0:
            # 이 칸 안에서 몇 번째인지로 low~bound 사이를 나눈다
            within = (target - seen) / count
            # 칸 위쪽 경계가 실제 최대보다 클 수 있다 — p99 가 최대값을 넘으면 거짓말이다
            return min(int(low + (bound - low) * within), max_ms)
        seen += count
        low = bound
    return max_ms  # 마지막 칸 — 경계를 넘긴 구간이라 최대값으로 답한다


@router.get(
    "/metrics/summary",
    response_model=ApiMetricsOut,
    dependencies=[Depends(require_role(Role.MASTER))],
)
async def metrics_summary(
    minutes: int = Query(60, ge=5, le=1440, description="최근 몇 분을 볼지"),
    db: AsyncSession = Depends(get_db),
) -> ApiMetricsOut:
    """최근 [minutes]분의 응답 지표.

    미들웨어가 **모든 요청**을 재서 분 단위로 모아 둔 것을 합친다
    (지표 조회 자체는 안 센다 — 보러 온 요청이 값을 흔들면 안 된다).
    """
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    bucket_cols = [func.coalesce(func.sum(getattr(ApiMetric, name)), 0) for name in _BUCKETS]
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(ApiMetric.count), 0),
                func.coalesce(func.sum(ApiMetric.errors), 0),
                func.coalesce(func.sum(ApiMetric.client_errors), 0),
                func.coalesce(func.sum(ApiMetric.sum_ms), 0),
                func.coalesce(func.max(ApiMetric.max_ms), 0),
                func.coalesce(func.sum(ApiMetric.over), 0),
                *bucket_cols,
            ).where(ApiMetric.minute >= since)
        )
    ).one()
    total, errors, client_errors, sum_ms, max_ms, over, *buckets = row
    counts = [int(b) for b in buckets]

    slow = (
        await db.execute(
            select(
                ApiMetric.method,
                ApiMetric.route,
                func.sum(ApiMetric.count).label("n"),
                func.sum(ApiMetric.sum_ms).label("sum_ms"),
                func.max(ApiMetric.max_ms).label("max_ms"),
                func.sum(ApiMetric.errors).label("errors"),
                *[func.sum(getattr(ApiMetric, name)) for name in _BUCKETS],
                func.sum(ApiMetric.over),
            )
            .where(ApiMetric.minute >= since)
            .group_by(ApiMetric.method, ApiMetric.route)
            .order_by((func.sum(ApiMetric.sum_ms) / func.sum(ApiMetric.count)).desc())
            .limit(10)
        )
    ).all()

    timeline = (
        await db.execute(
            select(
                ApiMetric.minute,
                func.sum(ApiMetric.count).label("n"),
                func.sum(ApiMetric.sum_ms).label("sum_ms"),
                func.sum(ApiMetric.errors).label("errors"),
            )
            .where(ApiMetric.minute >= since)
            .group_by(ApiMetric.minute)
            .order_by(ApiMetric.minute)
        )
    ).all()

    return ApiMetricsOut(
        minutes=minutes,
        requests=int(total),
        rpm=round(int(total) / minutes, 1),
        error_rate=round(int(errors) / int(total) * 100, 2) if total else 0.0,
        client_error_rate=round(int(client_errors) / int(total) * 100, 2) if total else 0.0,
        avg_ms=int(int(sum_ms) / int(total)) if total else 0,
        p50_ms=_percentile(counts, int(total), 0.50, int(max_ms)),
        p95_ms=_percentile(counts, int(total), 0.95, int(max_ms)),
        p99_ms=_percentile(counts, int(total), 0.99, int(max_ms)),
        max_ms=int(max_ms),
        slowest=[
            SlowRouteOut(
                method=r[0],
                route=r[1],
                count=int(r[2]),
                avg_ms=int(int(r[3]) / int(r[2])) if r[2] else 0,
                p95_ms=_percentile([int(x) for x in r[6 : 6 + len(BUCKET_BOUNDS)]], int(r[2]), 0.95, int(r[4])),
                max_ms=int(r[4]),
                errors=int(r[5]),
            )
            for r in slow
        ],
        timeline=[
            MetricPointOut(
                minute=r[0],
                count=int(r[1]),
                avg_ms=int(int(r[2]) / int(r[1])) if r[1] else 0,
                errors=int(r[3]),
            )
            for r in timeline
        ],
    )


@router.get(
    "/anomalies",
    response_model=list[AnomalyOut],
    dependencies=[Depends(require_role(Role.MASTER))],
)
async def list_anomalies(
    response: Response,
    unresolved_only: bool = Query(False, alias="unresolvedOnly"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    before: datetime | None = Query(None, description="장을 넘기는 동안 기준선 고정"),
    db: AsyncSession = Depends(get_db),
) -> list[Anomaly]:
    """찾아낸 이상행동 — 최신순. 접속·활동 로그와 같은 번호 페이지 방식이다.

    `X-Total-Count`  전체 건수 (탭 라벨 '전체 N')
    `X-Failed-Count` 아직 확인 안 한 건수 (탭 라벨 '미확인 N')
    """

    def narrowed(stmt):
        if before is not None:
            stmt = stmt.where(Anomaly.created_at <= before)
        return stmt

    total = await db.scalar(narrowed(select(func.count()).select_from(Anomaly)))
    open_count = await db.scalar(
        narrowed(select(func.count()).select_from(Anomaly)).where(Anomaly.resolved_at.is_(None))
    )
    response.headers["X-Total-Count"] = str(total or 0)
    response.headers["X-Failed-Count"] = str(open_count or 0)

    stmt = narrowed(select(Anomaly))
    if unresolved_only:
        stmt = stmt.where(Anomaly.resolved_at.is_(None))
    stmt = stmt.order_by(Anomaly.created_at.desc()).limit(limit).offset(offset)
    return list((await db.scalars(stmt)).all())


@router.post(
    "/anomalies/{anomaly_id}/resolve",
    response_model=AnomalyOut,
    dependencies=[Depends(require_role(Role.MASTER))],
)
async def resolve_anomaly(
    anomaly_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Anomaly:
    """'확인했다' 표시 — **MASTER 만.** 판단하는 자리라 ADMIN 은 보기만 한다."""
    anomaly = await db.get(Anomaly, anomaly_id)
    if anomaly is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "찾을 수 없습니다"})
    if anomaly.resolved_at is None:
        anomaly.resolved_at = datetime.now(timezone.utc)
        anomaly.resolved_by_id = current.id
        await db.commit()
        await db.refresh(anomaly)
    return anomaly


# ---------------------------------------------------------------------------
# 화면 캡처 신고 — **전 직원이 부른다** (위의 조회들과 달리 권한 게이트가 없다)
# ---------------------------------------------------------------------------


@router.post("/security/capture", status_code=204)
async def report_capture(
    body: CaptureReport,
    current: Employee = Depends(get_current_user),
) -> Response:
    """앱이 '화면이 찍혔다'고 알려 온다 — 받아 두기만 하면 된다.

    **여기서 따로 저장하지 않는다.** 쓰기 요청이라 `AuditMiddleware` 가
    이미 본문째 활동 로그에 남기고, `anomaly_scan` 이 그 줄을 세어
    짧은 시간에 여러 장 찍은 사람을 이상 징후로 올린다.

    막을 수 있는 플랫폼에서는 캡처가 아예 안 되므로 실제로는 iOS 만 부른다.
    MASTER 는 앱이 캡처 방지를 안 걸므로 신고도 안 보낸다.
    """
    del body, current  # 미들웨어가 다 적는다 — 여기서 쓸 일이 없다
    return Response(status_code=204)

# ---------------------------------------------------------------------------
# SSH 접속 알림 — **서버 자신이 부른다** (사람 로그인이 아니다)
# ---------------------------------------------------------------------------


@router.post("/security/ssh-login", status_code=204)
async def report_ssh_login(
    body: SshLoginReport,
    x_internal_token: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """서버에 SSH 로 누가 들어오면 **직급이 개발자인 사람에게** 알린다.

    부르는 쪽은 사람이 아니라 서버의 PAM 훅(`/usr/local/sbin/ssh-notify.sh`)이라,
    로그인 토큰이 아니라 `X-Internal-Token` 으로 확인한다.
    `internal_hook_token` 이 비어 있으면 **무조건 401** 이다 —
    설정을 빠뜨렸을 때 열려 있는 상태가 안 생긴다.

    **직급이 기준이고 권한이 아니다.** 서버를 만지는 사람에게만 가야 하는데,
    권한(MASTER)에는 대표도 들어가서 서버와 상관없는 사람에게까지 간다.

    실패해도 접속을 막지 않는다 — 훅 쪽이 백그라운드로 부르고 응답을 안 기다린다.
    """
    expected = settings.internal_hook_token
    if not expected or not secrets.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED"})

    devs = (
        await db.execute(
            select(Employee.id).where(
                Employee.rank == Rank.DEVELOPER,
                Employee.status == EmployeeStatus.ACTIVE,
            )
        )
    ).scalars().all()

    when = datetime.now(timezone(timedelta(hours=9))).strftime("%m/%d %H:%M")
    for employee_id in devs:
        await notify(
            db,
            employee_id=employee_id,
            type="SSH_LOGIN",
            title="서버 SSH 접속",
            body=f"{body.user}@서버 · {body.ip} · {when}",
            link="/monitoring",
        )
    await db.commit()
    return Response(status_code=204)

