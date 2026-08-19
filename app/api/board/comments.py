"""글 댓글 라우터 — 공지·회의록 공통 (2026-08-19).

반응(`/reactions`)과 **같은 다형 구조**다. 대상이 무엇이든 이 한 라우터가 받고,
볼 수 있는 글인지만 대상 종류별로 따로 가른다.

| 대상 | 볼 수 있는 사람 |
|---|---|
| 공지 | 전 직원 (공지는 원래 공용이다) |
| 회의록 | 그 회의록을 볼 수 있는 사람 (`meetings._can_view` 와 **같은 함수**) |
| 프로젝트 | 그 프로젝트를 볼 수 있는 사람 (`projects._ensure_visible` 와 **같은 함수**) |

**고치고 지우는 건 작성자 본인**이고, 관리자(MASTER·ADMIN·MANAGER)는 지우기만
된다 — 남의 말을 고쳐 쓰면 안 된다 (프로젝트 댓글과 같은 규칙이다).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.projects.meetings import _can_view
from app.api.projects.projects import _ensure_visible, _get_project_or_404
from app.core.deps import get_current_user
from app.db.session import get_db
from app.enums import CommentTargetType, Role
from app.models.board.comment import Comment
from app.models.board.notice import Notice
from app.models.projects.meeting import Meeting
from app.models.staff.employee import Employee
from app.schemas.board.comment import CommentCreate, CommentOut, CommentUpdate

router = APIRouter(prefix="/comments", tags=["comments"], dependencies=[Depends(get_current_user)])


def _out(row: Comment) -> CommentOut:
    return CommentOut(
        id=row.id,
        target_type=row.target_type,
        target_id=row.target_id,
        author_id=row.author_id,
        body=row.body,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _ensure_target_visible(
    db: AsyncSession, target_type: CommentTargetType, target_id: str, current: Employee
) -> None:
    """댓글을 달거나 읽을 수 있는 글인가 — **글 자체의 가시성을 그대로 쓴다.**

    여기서 규칙을 다시 적으면 회의록 공개 범위가 바뀔 때 댓글만 남아 새어 나간다.
    """
    if target_type is CommentTargetType.NOTICE:
        if await db.get(Notice, target_id) is None:
            raise HTTPException(404, detail={"code": "NOTICE_NOT_FOUND", "message": "공지를 찾을 수 없습니다"})
        return

    if target_type is CommentTargetType.PROJECT:
        # 완료됐는지는 안 본다 — 댓글은 완료 뒤에도 오간다(`_ensure_open` 예외)
        project = await _get_project_or_404(db, target_id)
        await _ensure_visible(db, project, current)
        return

    meeting = await db.get(Meeting, target_id)
    if meeting is None:
        raise HTTPException(404, detail={"code": "MEETING_NOT_FOUND", "message": "회의록을 찾을 수 없습니다"})
    if not await _can_view(db, meeting, current):
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "이 회의록을 볼 권한이 없습니다"})


async def count_comments(
    db: AsyncSession, target_type: CommentTargetType, target_ids: list[str]
) -> dict[str, int]:
    """글별 댓글 수 — 목록에서 N+1 없이 한 번에 (`aggregate_for` 와 같은 결)."""
    if not target_ids:
        return {}
    rows = (
        await db.execute(
            select(Comment.target_id, func.count())
            .where(
                Comment.target_type == target_type,
                Comment.target_id.in_(target_ids),
                Comment.deleted_at.is_(None),
            )
            .group_by(Comment.target_id)
        )
    ).all()
    counted = dict(rows)
    return {target_id: counted.get(target_id, 0) for target_id in target_ids}


@router.get("", response_model=list[CommentOut])
async def list_comments(
    target_type: CommentTargetType = Query(..., alias="targetType"),
    target_id: str = Query(..., alias="targetId"),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CommentOut]:
    """**오래된 것부터** — 글 아래 이야기가 위에서 아래로 흐른다.

    프로젝트 타임라인이 최신순인 것과 다르다. 저쪽은 '무슨 일이 있었나' 를
    훑는 기록이고 여기는 대화다.
    """
    await _ensure_target_visible(db, target_type, target_id, current)
    rows = (
        await db.execute(
            select(Comment)
            .where(
                Comment.target_type == target_type,
                Comment.target_id == target_id,
                Comment.deleted_at.is_(None),
            )
            .order_by(Comment.created_at)
        )
    ).scalars().all()
    return [_out(row) for row in rows]


@router.post("", response_model=CommentOut, status_code=201)
async def create_comment(
    payload: CommentCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommentOut:
    await _ensure_target_visible(db, payload.target_type, payload.target_id, current)
    row = Comment(
        target_type=payload.target_type,
        target_id=payload.target_id,
        author_id=current.id,
        body=payload.body,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _out(row)


async def _get_or_404(db: AsyncSession, comment_id: str) -> Comment:
    row = await db.get(Comment, comment_id)
    if row is None or row.deleted_at is not None:
        raise HTTPException(404, detail={"code": "COMMENT_NOT_FOUND", "message": "댓글을 찾을 수 없습니다"})
    return row


@router.patch("/{comment_id}", response_model=CommentOut)
async def update_comment(
    comment_id: str,
    payload: CommentUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CommentOut:
    row = await _get_or_404(db, comment_id)
    # **본인만 고친다** — 관리자도 남의 말을 고쳐 쓰지는 못한다
    if row.author_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 댓글만 수정할 수 있습니다"})
    await _ensure_target_visible(db, row.target_type, row.target_id, current)
    row.body = payload.body
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.delete("/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await _get_or_404(db, comment_id)
    # 본인 또는 관리자 — 프로젝트 댓글과 같은 기준이다
    if row.author_id != current.id and current.role not in (Role.MASTER, Role.ADMIN, Role.MANAGER):
        raise HTTPException(
            403, detail={"code": "FORBIDDEN", "message": "본인 댓글 또는 관리자만 삭제할 수 있습니다"}
        )
    await _ensure_target_visible(db, row.target_type, row.target_id, current)
    # 행은 남기고 표시만 — 모델에 적어 둔 이유(나중에 답글)와 같다
    row.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return None
