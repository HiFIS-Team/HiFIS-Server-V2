"""통합검색 라우터 — 프론트 검색 오버레이 (CLAUDE.md §6.13).

사람은 지점 스코프(MEMBER=본인 지점). 나머지(공지·회의록·프로젝트·문서)는 전사 공용.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import branch_scope, get_current_user
from app.db.session import get_db
from app.models.platform.document import Document
from app.models.staff.employee import Employee
from app.models.projects.meeting import Meeting
from app.models.board.notice import Notice
from app.models.projects.project import Project
from app.schemas.platform.search import DocumentHit, PersonHit, SearchResults, TitleHit

router = APIRouter(tags=["search"], dependencies=[Depends(get_current_user)])


@router.get("/search", response_model=SearchResults)
async def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
    scope_branch: str | None = Depends(branch_scope),  # MEMBER=본인 지점 / MANAGER·ADMIN=None
    db: AsyncSession = Depends(get_db),
) -> SearchResults:
    like = f"%{q}%"

    people_stmt = select(Employee).where(
        Employee.deleted_at.is_(None),
        or_(Employee.name.ilike(like), Employee.email.ilike(like)),
    )
    if scope_branch is not None:
        people_stmt = people_stmt.where(Employee.branch_id == scope_branch)
    people = (await db.scalars(people_stmt.order_by(Employee.name).limit(limit))).all()

    notices = (
        await db.scalars(
            select(Notice)
            .where(or_(Notice.title.ilike(like), Notice.body.ilike(like)))
            .order_by(Notice.created_at.desc())
            .limit(limit)
        )
    ).all()

    meetings = (
        await db.scalars(
            select(Meeting).where(Meeting.title.ilike(like)).order_by(Meeting.meeting_at.desc()).limit(limit)
        )
    ).all()

    projects = (
        await db.scalars(
            select(Project)
            .where(or_(Project.title.ilike(like), Project.purpose.ilike(like)))
            .order_by(Project.created_at.desc())
            .limit(limit)
        )
    ).all()

    documents = (
        await db.scalars(
            select(Document)
            .where(or_(Document.name.ilike(like), Document.desc.ilike(like)))
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
    ).all()

    return SearchResults(
        people=[PersonHit.model_validate(p) for p in people],
        notices=[TitleHit.model_validate(n) for n in notices],
        meetings=[TitleHit.model_validate(m) for m in meetings],
        projects=[TitleHit.model_validate(p) for p in projects],
        documents=[DocumentHit.model_validate(d) for d in documents],
    )
