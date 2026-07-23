"""Todo 라우터 — CLAUDE.md §6.2. 배정=[ADMIN,MANAGER], 완료=담당자/관리자."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_role
from app.db.session import get_db
from app.enums import Role
from app.models.org.employee import Employee
from app.models.collab.todo import Todo
from app.schemas.collab.todo import TodoCreate, TodoOut, TodoUpdate

router = APIRouter(prefix="/todos", tags=["todos"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[TodoOut])
async def list_todos(
    db: AsyncSession = Depends(get_db),
    assignee_id: str | None = Query(None, alias="assigneeId"),
    done: bool | None = Query(None),
) -> list[Todo]:
    stmt = select(Todo)
    if assignee_id:
        stmt = stmt.where(Todo.assignee_id == assignee_id)
    if done is not None:
        stmt = stmt.where(Todo.done == done)
    result = await db.execute(stmt.order_by(Todo.due_at))
    return list(result.scalars().all())


@router.post("", response_model=TodoOut, status_code=201)
async def create_todo(
    payload: TodoCreate,
    current: Employee = Depends(require_role(Role.ADMIN, Role.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> Todo:
    if await db.get(Employee, payload.assignee_id) is None:
        raise HTTPException(400, detail={"code": "ASSIGNEE_NOT_FOUND", "message": "담당자가 존재하지 않습니다"})
    todo = Todo(
        title=payload.title,
        due_at=payload.due_at,
        assignee_id=payload.assignee_id,
        assigned_by_id=current.id,
    )
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return todo


@router.patch("/{todo_id}", response_model=TodoOut)
async def update_todo(
    todo_id: str,
    payload: TodoUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Todo:
    todo = await db.get(Todo, todo_id)
    if todo is None:
        raise HTTPException(404, detail={"code": "TODO_NOT_FOUND", "message": "할일을 찾을 수 없습니다"})
    if current.role not in (Role.ADMIN, Role.MANAGER) and todo.assignee_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "본인 할일만 수정할 수 있습니다"})
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(todo, key, value)
    await db.commit()
    await db.refresh(todo)
    return todo
