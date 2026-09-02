"""추첨 게임 영상 굽기 — 인스타 릴스에 올리려고 만든다 (2026-09-01 대표 요청).

영상 일꾼(`tools/reels/`)이 헤드리스 크롬으로 클라이언트의 `/tv/{token}/reels`
를 열어 화면을 그대로 찍고 mp4 로 구워 준다. 여기서는 그걸 받아 `uploads/` 에
놓고 `draws.video_path` 에 적기만 한다.

## 왜 미리 만들어 두나

앱에서 버튼을 누른 뒤에 만들면 **1분을 기다려야 한다.** 추첨이 끝나는 매월
1일 새벽에 미리 구워 두면, 앱에서는 확인하고 공유만 한다.

## 왜 매일 도나

한 번만 돌면 그때 일꾼이 안 떠 있거나 클라이언트가 재배포 중이면 **그 달
영상이 영영 없다.** 이미 구운 것은 건너뛰므로 매일 돌아도 한 달에 세 번만
실제로 만든다.

## 왜 그냥 지나가나

`reels_url` 이 비어 있으면 조용히 넘어간다 — APNs·FCM 과 같은 규칙이다.
일꾼을 안 띄운 개발 서버에서 이 잡이 매일 에러를 뱉으면 안 된다.
"""

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.periods import now_kst
from app.core.storage import save_draw_video
from app.db.session import SessionLocal
from app.models.platform.draw import Draw
from app.models.staff.branch import Branch

log = logging.getLogger(__name__)

#: 한 판을 굽는 데 주는 시간(초) — 게임 40초 + 인코딩에 넉넉히
#:
#: 일꾼 쪽 상한(`MAX_SEC` 120초 + 180)보다 **짧게** 둔다. 저쪽이 스스로
#: 끊게 두는 게 낫다 — 여기서 먼저 끊으면 일꾼은 계속 굽고 있고 다음 지점이
#: `BUSY` 로 튕긴다.
TIMEOUT = 280.0

#: 몇 달 치까지 돌아보나 — 지난달 것이 비어 있으면 채워 준다
BACKFILL = 2


def _months(period: str, back: int) -> list[str]:
    """`2026-09` 에서 거슬러 `back` 달치 — 새것부터."""
    year, month = int(period[:4]), int(period[5:7])
    out = []
    for _ in range(back):
        out.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


async def _make(client: httpx.AsyncClient, db: AsyncSession, draw: Draw, token: str) -> bool:
    """한 판을 구워 [Draw.video_path] 에 적는다 — 성공하면 True."""
    headers = {"X-Render-Token": settings.render_token} if settings.render_token else {}
    res = await client.post("/render", json={"token": token}, headers=headers, timeout=TIMEOUT)
    if res.status_code != 200:
        log.warning("영상 실패 %s %s — %s %s", draw.period, token, res.status_code, res.text[:200])
        return False
    draw.video_path = save_draw_video(res.content)
    draw.video_at = now_kst()
    log.info(
        "영상 %s %s — %.1fMB (%s초)",
        draw.period,
        draw.video_path,
        len(res.content) / 1024 / 1024,
        res.headers.get("x-render-seconds", "?"),
    )
    return True


async def draw_videos() -> None:
    """아직 영상이 없는 추첨을 찾아 굽는다 — 매일 새벽에 돈다."""
    if not settings.reels_url:
        return

    period = f"{now_kst().year:04d}-{now_kst().month:02d}"
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Draw, Branch)
                .join(Branch, Branch.id == Draw.branch_id)
                .where(
                    Draw.period.in_(_months(period, BACKFILL)),
                    Draw.video_path.is_(None),
                )
                .order_by(Draw.period.desc())
            )
        ).all()
        # 참가자가 없는 달은 화면에 게임이 안 떠서 찍을 것이 없다
        todo = [(d, b) for d, b in rows if d.entries and d.winner_indexes and b.tv_token]
        if not todo:
            return

        async with httpx.AsyncClient(base_url=settings.reels_url.rstrip("/")) as client:
            for draw, branch in todo:
                try:
                    await _make(client, db, draw, branch.tv_token)
                except Exception:  # noqa: BLE001 — 한 지점이 실패해도 나머지는 굽는다
                    log.exception("영상 실패 %s %s", branch.name, draw.period)
        await db.commit()


__all__ = ["draw_videos"]
