"""환경정비 라우터 — EnvItem/EnvTaskLog/SupplyOrder (CLAUDE.md §4.2).

- 항목 정의: [ADMIN,MANAGER] / 수행(env-logs POST): [MEMBER,MANAGER] (점장도 정비 수행. ADMIN·MASTER 제외).
- 수행 → ENV 점수 적립, 취소(DELETE) → 연결 점수 회수.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_filter, branch_pick, branch_scope, get_current_user, require_role
from app.core.periods import KST, period_range
from app.core.storage import save_env_photo
from app.db.session import get_db
from app.enums import Role, ScoreCategory
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.models.scoring.env import EnvItem, EnvTaskLog, SupplyOrder
from app.models.scoring.score_event import ScoreEvent
from app.schemas.scoring.env import (
    EnvItemCreate,
    EnvItemOut,
    EnvItemUpdate,
    EnvLogAward,
    EnvLogCreate,
    EnvLogPhotoOut,
    EnvTaskLogOut,
    SupplyOrderCreate,
    SupplyOrderOut,
)
from app.services import notification_texts as ntext
from app.services.notifications import notify
from app.services.scoring import accrue_score

router = APIRouter(tags=["env"])


# 기본 환경정비 항목 (최종 점수표). 지점마다 없으면 자동 생성 —
# (이름, 배점, editable). editable=False 는 고정 보호(수정/삭제 불가).
# '기타'는 1~10 범위라 editable=True 로 두어 지점별 조정 가능(항목을 바꾸려면 이 상수를 고칠 것).
# 순서 = 하루 일하는 흐름(§31): 빨래 → 청소 → 관리 → 홍보 → 기타.
# (배점순 아님 — 현수막이 청소 사이에 끼거나 화장실청소가 홍보 뒤로 가지 않도록)
#
# **이 차례는 앱이 정한다.** 칩을 위에서 아래로 훑으며 누르게 돼 있어서
# 실제 일하는 차례와 다르면 손이 왔다 갔다 한다. 임의로 바꾸지 않는다.
BASE_ENV_ITEMS: list[tuple[str, int, bool]] = [
    # 빨래 — 돌리고, 말리고, 갠다. 이 차례가 뒤집히면 안 된다
    ("세탁", 1, False),
    ("건조기", 1, False),
    ("빨래정리", 2, False),   # 3 → 2 (2026-08-13 대표 결정)
    # 청소 — 넓은 곳부터 탈의실, 화장실 순
    ("구역청소", 2, False),
    ("복도청소", 2, False),
    ("락커정리", 2, False),
    ("남탈부스", 5, False),
    ("남탈청소", 2, False),
    ("여탈부스", 5, False),
    ("여탈청소", 2, False),
    ("화장실청소", 2, False),  # 5 → 2 (2026-08-13 대표 결정)
    # 관리
    ("기구관리", 2, False),
    ("회원지도", 2, False),
    ("TM회원관리", 5, False),  # 1 → 5 (2026-08-14 대표 결정)
    # 홍보 — 온라인부터 오프라인
    ("게시물", 3, False),
    ("스토리", 2, False),  # 3 → 2 (2026-08-28 대표 결정)
    ("전단지", 1, False),  # 10 → 1 (2026-08-19 대표 결정)
    ("현수막", 10, False),
    ("족자", 5, False),
    ("블로그", 3, False),  # 10 → 3 + 대표 가산점 (2026-08-28 대표 결정)
    # 기타 — 어쩌다 하는 것들
    # 컴플레인 한 건을 끝까지 처리한 값이라 다른 항목보다 높다 (2026-08-31 대표 요청)
    ("클레임해결", 15, False),
    ("기타", 1, True),  # 1~10 범위 → 지점별 조정 가능
]


# 사진과 위치를 **반드시** 받아야 하는 항목 (2026-08-18 대표 요청).
#
# 걸었다고 칩만 누르면 실제로 걸었는지 확인할 방법이 없다. 눈으로 확인되는
# 것만 점수로 인정하려는 것이라, 안 채우면 기록 자체를 안 만든다.
#
# **여기 없는 항목은 지금처럼 그냥 눌러 남긴다.** 늘리려면 이 집합에 이름을
# 더하고 **앱의 `_photoRequiredItems` 도 같이 고친다** — 한쪽만 늘리면
# 그 칩이 앱에서는 사진을 안 받고 눌렀는데 서버가 400 으로 되돌려 보낸다.
#
# **족자도 받는다 (2026-08-21 요청).** 현수막과 같은 종류다 — 걸어 두는 것이라
# 눌렀다고 실제로 걸렸는지 확인할 길이 사진뿐이다.
#
# **전단지도 받는다 (2026-09-02 대표 요청).** 예전에는 "돌리는 것이라 걸린
# 자리가 없다" 고 뺐는데, 확인할 길이 없는 건 마찬가지라 셋을 같은 모양으로
# 맞췄다.
PHOTO_REQUIRED_ITEMS = {"현수막", "족자", "전단지"}

# 글 주소를 같이 받는 항목 — **블로그뿐이다** (2026-08-28 대표 요청).
#
# 배점을 10 → 3 으로 내리는 대신 대표가 글을 보고 가산점을 얹기로 했는데,
# 링크가 없으면 무엇을 보고 매길지가 없다.
#
# **사진과 달리 필수가 아니다.** 주소가 아직 없어도 남길 수는 있어야 한다 —
# 막으면 글은 썼는데 기록을 못 하는 날이 생긴다.
LINK_ITEMS = {"블로그"}

# 대표가 가산점을 얹을 수 있는 항목 — 지금은 블로그뿐이다.
# 늘리려면 여기에 이름만 더한다 (앱의 `_awardableItems` 도 같이).
AWARDABLE_ITEMS = {"블로그"}


def _env_key(name: str) -> str:
    """항목 이름 비교용 — 공백을 떼고 소문자로. 앱의 `_envKey` 와 같은 규칙이다."""
    return name.replace(" ", "").lower()


_PHOTO_REQUIRED_KEYS = {_env_key(n) for n in PHOTO_REQUIRED_ITEMS}
_LINK_KEYS = {_env_key(n) for n in LINK_ITEMS}
_AWARDABLE_KEYS = {_env_key(n) for n in AWARDABLE_ITEMS}


def _needs_photo(item: EnvItem) -> bool:
    return _env_key(item.name) in _PHOTO_REQUIRED_KEYS


def _takes_link(item: EnvItem) -> bool:
    return _env_key(item.name) in _LINK_KEYS


async def _ensure_base_items(db: AsyncSession, branch_id: str) -> None:
    """지점에 환경정비 항목이 하나도 없으면 기본 항목을 심는다 (멱등).

    DB 초기화/부분 삭제 후에도 첫 조회 때 자동 복구 → 수동 재시드 불필요.
    """
    existing = await db.execute(select(EnvItem.id).where(EnvItem.branch_id == branch_id).limit(1))
    if existing.first() is not None:
        return
    if await db.get(Branch, branch_id) is None:  # 실재하는 지점만
        return
    for i, (name, points, editable) in enumerate(BASE_ENV_ITEMS):
        db.add(EnvItem(branch_id=branch_id, name=name, points=points, editable=editable, sort_order=i))
    await db.commit()


# ---------- EnvItem (항목·배점) ----------
@router.get("/env-items", response_model=list[EnvItemOut], dependencies=[Depends(get_current_user)])
async def list_env_items(
    db: AsyncSession = Depends(get_db),
    # **점검 항목(칩)은 늘 본인 지점이다** — 누르는 것이라 남의 지점 것이
    # 떠 봐야 403 이다(아래 `create_env_log`). 게다가 항목 22개가 지점마다
    # 한 벌씩 있어서 전 지점으로 받으면 **같은 항목이 지점 수만큼 겹친다.**
    # 기록(`/env-logs`)만 고른 지점을 따라간다.
    scope: str | None = Depends(branch_filter),
) -> list[EnvItem]:
    # 기본 항목 자동 보충: 특정 지점이 대상이면 그 지점, 아니면(ADMIN 전체 조회) 모든 지점
    if scope:
        await _ensure_base_items(db, scope)
    else:
        for (bid,) in (await db.execute(select(Branch.id))).all():
            await _ensure_base_items(db, bid)

    stmt = select(EnvItem)
    if scope:
        stmt = stmt.where(EnvItem.branch_id == scope)
    result = await db.execute(stmt.order_by(EnvItem.sort_order, EnvItem.name))  # 고정 순서(§4.2 #31)
    return list(result.scalars().all())


@router.post("/env-items", response_model=EnvItemOut, status_code=201, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def create_env_item(payload: EnvItemCreate, db: AsyncSession = Depends(get_db)) -> EnvItem:
    if await db.get(Branch, payload.branch_id) is None:
        raise HTTPException(400, detail={"code": "BRANCH_NOT_FOUND", "message": "지점이 존재하지 않습니다"})
    item = EnvItem(
        branch_id=payload.branch_id, name=payload.name, points=payload.points,
        editable=payload.editable, sort_order=payload.sort_order,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/env-items/{item_id}", response_model=EnvItemOut, dependencies=[Depends(require_role(Role.ADMIN, Role.MANAGER))])
async def update_env_item(
    item_id: str, payload: EnvItemUpdate, db: AsyncSession = Depends(get_db)
) -> EnvItem:
    item = await db.get(EnvItem, item_id)
    if item is None:
        raise HTTPException(404, detail={"code": "ENV_ITEM_NOT_FOUND", "message": "환경정비 항목을 찾을 수 없습니다"})
    if not item.editable:  # 기본 고정 항목은 수정 불가 (삭제는 엔드포인트 자체가 없음)
        raise HTTPException(403, detail={"code": "ENV_ITEM_LOCKED", "message": "기본 항목은 수정할 수 없습니다"})
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


# ---------- EnvTaskLog (수행 기록 → 점수) ----------
@router.post("/env-logs/photo", response_model=EnvLogPhotoOut, status_code=201)
async def upload_env_photo(
    file: UploadFile = File(...),
    # 수행하는 사람과 같은 권한 — 올릴 수 있는 사람이 남길 수 있는 사람이다
    current: Employee = Depends(require_role(Role.MEMBER, Role.MANAGER)),
) -> EnvLogPhotoOut:
    """수행 사진을 먼저 올리고 주소를 받는다 → 그 주소를 `POST /env-logs` 에 실어 보낸다.

    **기록 만들기와 나눈 이유** — `POST /env-logs` 는 지금 JSON 을 받는데
    파일을 실으려면 multipart 로 바꿔야 한다. 그러면 이미 나가 있는 앱의
    모든 환경정비 칩이 같이 깨진다. 사진이 필요한 건 한 항목뿐이라
    그 항목만 한 번 더 부르는 쪽이 싸다.

    올려 놓고 기록을 안 만들면 파일만 남는다 — 큰 문제는 아니지만
    쌓이면 청소가 필요할 수 있다 (지금은 안 지운다).
    """
    return EnvLogPhotoOut(url=await save_env_photo(file))


@router.post("/env-logs", response_model=EnvTaskLogOut, status_code=201)
async def create_env_log(
    payload: EnvLogCreate,
    # 점장(MANAGER)도 정비를 수행함 → 허용. ADMIN·MASTER 는 운영 전담이라 제외(세션 싸인과 동일).
    current: Employee = Depends(require_role(Role.MEMBER, Role.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> EnvTaskLog:
    item = await db.get(EnvItem, payload.env_item_id)
    if item is None:
        raise HTTPException(400, detail={"code": "ENV_ITEM_NOT_FOUND", "message": "환경정비 항목이 존재하지 않습니다"})
    # 남의 지점 항목은 수행으로 안 받는다. MANAGER 가 헤더 고르개로 다른 지점을
    # 볼 수 있게 되면서(`branch_pick`) 생긴 자리다 — 그 지점 칩을 누르면
    # `branch_id=item.branch_id` 라 **남의 지점에 내 점수가 쌓인다.**
    # 보는 것만 열고 하는 것은 본인 지점에 둔다.
    if item.branch_id != current.branch_id:
        raise HTTPException(403, detail={"code": "OTHER_BRANCH", "message": "다른 지점의 항목은 수행할 수 없습니다"})
    # 현수막처럼 확인이 필요한 항목은 **사진과 위치가 없으면 기록을 안 만든다.**
    # 앱에서도 막지만 여기서 다시 본다 — 앱을 안 거치고 부르면 그냥 통과한다.
    place = (payload.place or "").strip()
    if _needs_photo(item) and (not payload.photo_url or not place):
        raise HTTPException(
            400,
            detail={
                "code": "PHOTO_REQUIRED",
                "message": f"{item.name}은(는) 사진과 위치를 함께 남겨야 합니다",
            },
        )
    # 블로그 주소 — 안 보내도 되지만, 보냈으면 진짜 주소여야 한다.
    # 링크를 안 받는 항목에 실려 오면 **조용히 버린다** (엉뚱한 칸이 채워지면
    # 나중에 그 항목도 링크를 받는 줄 알게 된다).
    link = (payload.link or "").strip() or None
    if link is not None and not _takes_link(item):
        link = None
    if link is not None and not link.lower().startswith(("http://", "https://")):
        raise HTTPException(
            400,
            detail={"code": "BAD_LINK", "message": "글 주소는 http:// 또는 https:// 로 시작해야 합니다"},
        )
    # 기타 등 write-in: 적은 내용을 라벨에 접어 "기타(창고정리)" 로 스냅샷(점수 원장·랭킹 사유도 동일). item_name String(100) 보호.
    label = f"{item.name}({payload.note})"[:100] if payload.note else item.name
    log = EnvTaskLog(
        employee_id=current.id,
        branch_id=item.branch_id,
        env_item_id=item.id,
        item_name=label,
        points=item.points,
        note=payload.note,
        photo_url=payload.photo_url,
        place=place or None,
        link=link,
    )
    db.add(log)
    await db.flush()
    await accrue_score(
        db,
        employee_id=current.id,
        branch_id=item.branch_id,
        category=ScoreCategory.ENV,
        points=item.points,
        created_by_id=current.id,
        source_ref_id=log.id,
        reason=label,
    )
    await db.commit()
    await db.refresh(log)
    return log


@router.get("/env-logs", response_model=list[EnvTaskLogOut], dependencies=[Depends(get_current_user)])
async def list_env_logs(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_pick),
    employee_id: str | None = Query(None, alias="employeeId"),
    date: str | None = Query(None),      # "YYYY-MM-DD" — 하루치(KST). 앱 '오늘' 필터
    period: str | None = Query(None),    # "YYYY-MM" — 월치(세션 싸인과 동일)
) -> list[EnvTaskLog]:
    stmt = select(EnvTaskLog)
    if scope:
        stmt = stmt.where(EnvTaskLog.branch_id == scope)
    if employee_id:
        stmt = stmt.where(EnvTaskLog.employee_id == employee_id)
    if date:
        try:
            d = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, detail={"code": "INVALID_DATE", "message": "date 형식은 YYYY-MM-DD 입니다"})
        day_start = datetime(d.year, d.month, d.day, tzinfo=KST)  # KST 하루 → created_at(UTC) 비교
        stmt = stmt.where(EnvTaskLog.created_at >= day_start, EnvTaskLog.created_at < day_start + timedelta(days=1))
    if period:
        start, end = period_range(period)
        stmt = stmt.where(EnvTaskLog.created_at >= start, EnvTaskLog.created_at < end)
    result = await db.execute(stmt.order_by(EnvTaskLog.created_at.desc()))
    return list(result.scalars().all())


@router.post("/env-logs/{log_id}/award", response_model=EnvTaskLogOut)
async def award_env_log(
    log_id: str,
    payload: EnvLogAward,
    # **MASTER 만이다.** 프로젝트 점수 부여와 같은 자리다 — 잘했는지를
    # 판단하는 일이라 한 사람이 한다.
    current: Employee = Depends(require_role(Role.MASTER)),
    db: AsyncSession = Depends(get_db),
) -> EnvTaskLog:
    """블로그 가산점 — 기본 배점 **위에 얹는다** (2026-08-28 대표 요청).

    배점을 10 → 3 으로 내린 대신 대표가 글을 보고 얹는다. 기본 3 + 가산 7 이면
    최종 10 이다. 다시 부르면 **갈아끼운다** (더해지지 않는다) — 두 번 눌러서
    점수가 두 배가 되면 되돌릴 방법이 없다.

    `points = 0` 이면 가산점을 걷는다. 음수도 받지만 **최종 점수는 0 아래로
    안 내려간다** — 환경정비를 해서 점수가 깎이는 일은 없어야 한다.

    점수 원장에는 `기본 + 가산` 을 **한 줄로** 쓴다. 두 줄로 나누면 기록을
    지울 때(`DELETE /env-logs/{id}`) 한쪽만 걷힐 자리가 생긴다.
    """
    log = await db.get(EnvTaskLog, log_id)
    if log is None:
        raise HTTPException(404, detail={"code": "ENV_LOG_NOT_FOUND", "message": "수행 기록을 찾을 수 없습니다"})

    # 어떤 항목이었는지는 **`env_item_id` 로** 본다. `item_name` 은 '기타(창고정리)'
    # 처럼 메모가 접혀 들어갈 수 있어서 이름 비교가 어긋난다.
    item = await db.get(EnvItem, log.env_item_id)
    name = item.name if item is not None else log.item_name.split("(")[0]
    if _env_key(name) not in _AWARDABLE_KEYS:
        raise HTTPException(
            400,
            detail={"code": "NOT_AWARDABLE", "message": f"{name}에는 가산점을 줄 수 없습니다"},
        )

    log.bonus_points = payload.points
    log.bonus_reason = payload.comment.strip()
    log.bonus_by_id = current.id
    log.bonus_at = datetime.now(KST)

    # 원장 한 줄을 최종 점수로 갈아끼운다 — 0 아래로는 안 내린다
    total = max(0, log.points + log.bonus_points)
    event = await db.scalar(
        select(ScoreEvent).where(
            ScoreEvent.category == ScoreCategory.ENV,
            ScoreEvent.source_ref_id == log.id,
        )
    )
    if event is not None:
        event.points = total
        event.reason = f"{log.item_name} · {log.bonus_reason}"
        # `created_by_id` 는 **안 바꾼다** — 그 일을 한 사람이 누구였는지가
        # 원장의 뜻이다. 누가 매겼는지는 기록(`bonus_by_id`)에 남는다

    # 받은 사람에게 알린다 — 점수가 바뀌었는데 아무 표시가 없으면 모른다
    await notify(db, employee_id=log.employee_id, **ntext.env_award(name, total, log.bonus_reason))

    await db.commit()
    await db.refresh(log)
    return log


@router.delete("/env-logs/{log_id}", status_code=204)
async def delete_env_log(
    log_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    log = await db.get(EnvTaskLog, log_id)
    if log is None:
        raise HTTPException(404, detail={"code": "ENV_LOG_NOT_FOUND", "message": "수행 기록을 찾을 수 없습니다"})
    if current.role not in (Role.MASTER, Role.ADMIN, Role.MANAGER) and log.employee_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 기록만 취소할 수 있습니다"})
    # 연결된 ENV 점수 회수 (− 취소)
    await db.execute(
        delete(ScoreEvent).where(
            ScoreEvent.source_ref_id == log.id, ScoreEvent.category == ScoreCategory.ENV
        )
    )
    await db.delete(log)
    await db.commit()
    return None


# ---------- SupplyOrder (비품) ----------
@router.post("/supply-orders", response_model=SupplyOrderOut, status_code=201)
async def create_supply_order(
    payload: SupplyOrderCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupplyOrder:
    if await db.get(Branch, payload.branch_id) is None:
        raise HTTPException(400, detail={"code": "BRANCH_NOT_FOUND", "message": "지점이 존재하지 않습니다"})
    order = SupplyOrder(
        branch_id=payload.branch_id,
        item_name=payload.item_name,
        price=payload.price,
        ordered_by_id=current.id,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


@router.get("/supply-orders", response_model=list[SupplyOrderOut], dependencies=[Depends(get_current_user)])
async def list_supply_orders(
    db: AsyncSession = Depends(get_db),
    scope: str | None = Depends(branch_scope),
    branch_id: str | None = Query(None, alias="branchId"),
    month: str | None = Query(None),
) -> list[SupplyOrder]:
    stmt = select(SupplyOrder)
    if scope:
        stmt = stmt.where(SupplyOrder.branch_id == scope)
    if branch_id:
        stmt = stmt.where(SupplyOrder.branch_id == branch_id)
    if month:
        start, end = period_range(month)
        stmt = stmt.where(SupplyOrder.created_at >= start, SupplyOrder.created_at < end)
    result = await db.execute(stmt.order_by(SupplyOrder.created_at.desc()))
    return list(result.scalars().all())
