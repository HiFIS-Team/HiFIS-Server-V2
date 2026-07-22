"""Approval 라우터 — 전자결재 순차 결재선 (CLAUDE.md §6.5).

JSONB(steps/comments)는 in-place 변경 감지가 안 돼 새 리스트로 재할당한다.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.enums import ApprovalStatus, ApprovalStepStatus
from app.models.approval import Approval
from app.models.employee import Employee
from app.schemas.approval import ApprovalAction, ApprovalCreate, ApprovalOut, CommentCreate
from app.services.notifications import notify

router = APIRouter(prefix="/approvals", tags=["approvals"], dependencies=[Depends(get_current_user)])


def _mark_step(steps: list, approver_id: str, decision: ApprovalStepStatus, comment: str | None, acted_at: str) -> list:
    result = []
    for step in steps:
        if step["approver_id"] == approver_id and step["status"] == ApprovalStepStatus.PENDING:
            result.append({**step, "status": decision, "comment": comment, "acted_at": acted_at})
        else:
            result.append(step)
    return result


async def _get_or_404(approval_id: str, db: AsyncSession) -> Approval:
    approval = await db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(404, detail={"code": "APPROVAL_NOT_FOUND", "message": "결재 문서를 찾을 수 없습니다"})
    return approval


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    box: str = Query(..., pattern="^(mine|inbox)$"),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Approval]:
    stmt = select(Approval)
    if box == "mine":
        stmt = stmt.where(Approval.requester_id == current.id)
    else:  # inbox — 내 결재 차례인 문서
        stmt = stmt.where(
            Approval.current_approver_id == current.id,
            Approval.status == ApprovalStatus.IN_PROGRESS,
        )
    result = await db.execute(stmt.order_by(Approval.created_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=ApprovalOut, status_code=201)
async def create_approval(
    payload: ApprovalCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Approval:
    steps = [
        {"approver_id": aid, "status": ApprovalStepStatus.PENDING, "comment": None, "acted_at": None}
        for aid in payload.approver_ids
    ]
    approval = Approval(
        kind=payload.kind,
        title=payload.title,
        content=payload.content,
        amount=payload.amount,
        start_date=payload.start_date,
        end_date=payload.end_date,
        place=payload.place,
        requester_id=current.id,
        approver_ids=payload.approver_ids,
        steps=steps,
        current_approver_id=payload.approver_ids[0],
        comments=[],
    )
    db.add(approval)
    await db.flush()  # approval.id 확보(알림 링크용)
    await notify(
        db,
        employee_id=payload.approver_ids[0],
        type="APPROVAL",
        title="결재 요청이 도착했습니다",
        body=payload.title,
        link=f"/approvals/{approval.id}",
    )
    await db.commit()
    await db.refresh(approval)
    return approval


@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(approval_id: str, db: AsyncSession = Depends(get_db)) -> Approval:
    return await _get_or_404(approval_id, db)


async def _act(approval_id: str, decision: ApprovalStepStatus, comment: str | None, current: Employee, db: AsyncSession) -> Approval:
    approval = await _get_or_404(approval_id, db)
    if approval.status != ApprovalStatus.IN_PROGRESS:
        raise HTTPException(400, detail={"code": "ALREADY_DONE", "message": "이미 종결된 결재입니다"})
    if approval.current_approver_id != current.id:
        raise HTTPException(403, detail={"code": "NOT_YOUR_TURN", "message": "결재 차례가 아닙니다"})

    now_iso = datetime.now(timezone.utc).isoformat()
    approval.steps = _mark_step(approval.steps, current.id, decision, comment, now_iso)

    link = f"/approvals/{approval.id}"
    if decision == ApprovalStepStatus.REJECTED:
        approval.status = ApprovalStatus.REJECTED
        approval.current_approver_id = None
        await notify(db, employee_id=approval.requester_id, type="APPROVAL",
                     title="결재가 반려되었습니다", body=approval.title, link=link)
    else:
        index = approval.approver_ids.index(current.id)
        if index + 1 < len(approval.approver_ids):
            approval.current_approver_id = approval.approver_ids[index + 1]  # 다음 결재자
            await notify(db, employee_id=approval.current_approver_id, type="APPROVAL",
                         title="결재 요청이 도착했습니다", body=approval.title, link=link)
        else:
            approval.status = ApprovalStatus.APPROVED  # 마지막 → 최종 승인
            approval.current_approver_id = None
            await notify(db, employee_id=approval.requester_id, type="APPROVAL",
                         title="결재가 최종 승인되었습니다", body=approval.title, link=link)
    await db.commit()
    await db.refresh(approval)
    return approval


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve_approval(
    approval_id: str,
    payload: ApprovalAction,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Approval:
    return await _act(approval_id, ApprovalStepStatus.APPROVED, payload.comment, current, db)


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject_approval(
    approval_id: str,
    payload: ApprovalAction,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Approval:
    return await _act(approval_id, ApprovalStepStatus.REJECTED, payload.comment, current, db)


@router.post("/{approval_id}/comments", response_model=ApprovalOut)
async def add_comment(
    approval_id: str,
    payload: CommentCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Approval:
    approval = await _get_or_404(approval_id, db)
    now_iso = datetime.now(timezone.utc).isoformat()
    approval.comments = approval.comments + [
        {"author_id": current.id, "body": payload.body, "created_at": now_iso}
    ]
    await db.commit()
    await db.refresh(approval)
    return approval
