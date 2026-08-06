"""문서함 라우터 — Folder/Document + 멀티파트 업로드·다운로드 (CLAUDE.md §6.6, §9.2)."""

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.storage import save_upload
from app.db.session import get_db
from app.enums import Role
from app.models.platform.document import Document, Folder
from app.models.platform.document_favorite import DocumentFavorite
from app.models.staff.employee import Employee
from app.schemas.platform.document import (
    DocumentOut,
    DocumentUpdate,
    FolderCreate,
    FolderOut,
    FolderTreeCreate,
    FolderTreeNode,
    FolderTreeNodeOut,
    FolderUpdate,
)

router = APIRouter(tags=["documents"], dependencies=[Depends(get_current_user)])


def _parse_tags(raw: str | None) -> list[str]:
    return [t.strip() for t in raw.split(",")] if raw and raw.strip() else []


def _forbidden() -> HTTPException:
    return HTTPException(403, detail={"code": "FORBIDDEN", "message": "작성자 또는 관리자만 가능합니다"})


#: 개인 문서함 갈래 — 이 값이면 **올린 사람만** 보고 만진다.
#: `scope` 는 원래 조회 필터일 뿐이었는데, 개인 문서를 담게 되면서
#: 이 값 하나만 실제 권한이 됐다. **MASTER 도 남의 개인 문서는 못 본다.**
PERSONAL_SCOPE = "개인"


def _personal_blocked() -> HTTPException:
    return HTTPException(
        403, detail={"code": "PERSONAL_DOC", "message": "다른 사람의 개인 문서예요"}
    )


def _mine_only(stmt, scope_col, owner_col, current: Employee):
    """목록에서 남의 개인 문서·폴더를 걸러 낸다.

    요청자가 `?scope=` 를 뭘 넣든 상관없이 항상 건다 — 필터는 요청자가 고르는
    값이라 그것만 믿으면 `?scope=개인` 한 번으로 전부 새어 나간다.
    """
    return stmt.where(or_(scope_col != PERSONAL_SCOPE, owner_col == current.id))


def _ensure_mine(scope: str, owner_id: str, current: Employee) -> None:
    """단건 접근 — 개인 갈래면 주인만 통과한다."""
    if scope == PERSONAL_SCOPE and owner_id != current.id:
        raise _personal_blocked()


async def _descendant_folder_ids(db: AsyncSession, root_id: str) -> set[str]:
    """root 아래 모든 하위 폴더 id (root 자신은 제외). BFS."""
    seen: set[str] = set()
    frontier = [root_id]
    while frontier:
        rows = (
            await db.execute(select(Folder.id).where(Folder.parent_id.in_(frontier)))
        ).scalars().all()
        fresh = [r for r in rows if r not in seen]
        seen.update(fresh)
        frontier = fresh
    return seen


async def _docs_out(
    db: AsyncSession, documents: list[Document], current: Employee
) -> list[DocumentOut]:
    """DocumentOut + favoritedByMe 배치 계산."""
    ids = [d.id for d in documents]
    fav: set[str] = set()
    if ids:
        rows = (
            await db.execute(
                select(DocumentFavorite.document_id).where(
                    DocumentFavorite.document_id.in_(ids),
                    DocumentFavorite.employee_id == current.id,
                )
            )
        ).scalars().all()
        fav = set(rows)
    out: list[DocumentOut] = []
    for d in documents:
        model = DocumentOut.model_validate(d)
        model.favorited_by_me = d.id in fav
        out.append(model)
    return out


# ---------- Folder ----------
@router.get("/folders", response_model=list[FolderOut])
async def list_folders(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    space: str | None = Query(None),
    scope: str | None = Query(None),
) -> list[Folder]:
    stmt = select(Folder)
    if space:
        stmt = stmt.where(Folder.space == space)
    if scope:
        stmt = stmt.where(Folder.scope == scope)
    stmt = _mine_only(stmt, Folder.scope, Folder.created_by_id, current)
    result = await db.execute(stmt.order_by(Folder.name))
    return list(result.scalars().all())


@router.post("/folders", response_model=FolderOut, status_code=201)
async def create_folder(
    payload: FolderCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Folder:
    if payload.parent_id and await db.get(Folder, payload.parent_id) is None:
        raise HTTPException(400, detail={"code": "FOLDER_NOT_FOUND", "message": "상위 폴더가 존재하지 않습니다"})
    folder = Folder(
        name=payload.name,
        scope=payload.scope,
        space=payload.space,
        parent_id=payload.parent_id,
        created_by_id=current.id,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


@router.post("/folders/tree", response_model=list[FolderTreeNodeOut], status_code=201)
async def create_folder_tree(
    payload: FolderTreeCreate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FolderTreeNodeOut]:
    """폴더째 업로드 — 폴더 트리를 한 트랜잭션으로 생성(중간 실패 시 전체 롤백).

    반환은 입력과 같은 트리 구조 + 새 id → 앱이 로컬 경로별로 파일을 각 폴더에 올린다.
    """
    if payload.parent_id and await db.get(Folder, payload.parent_id) is None:
        raise HTTPException(400, detail={"code": "FOLDER_NOT_FOUND", "message": "붙일 상위 폴더가 존재하지 않습니다"})

    async def _create(nodes: list[FolderTreeNode], parent_id: str | None) -> list[FolderTreeNodeOut]:
        created: list[FolderTreeNodeOut] = []
        for node in nodes:
            folder = Folder(
                name=node.name,
                scope=payload.scope,
                space=payload.space,
                parent_id=parent_id,
                created_by_id=current.id,
            )
            db.add(folder)
            await db.flush()  # id 확보
            children = await _create(node.children, folder.id)
            created.append(FolderTreeNodeOut(id=folder.id, name=folder.name, children=children))
        return created

    tree = await _create(payload.nodes, payload.parent_id)
    await db.commit()
    return tree


@router.patch("/folders/{folder_id}", response_model=FolderOut)
async def update_folder(
    folder_id: str,
    payload: FolderUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Folder:
    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(404, detail={"code": "FOLDER_NOT_FOUND", "message": "폴더를 찾을 수 없습니다"})
    _ensure_mine(folder.scope, folder.created_by_id, current)
    if current.role not in (Role.MASTER, Role.ADMIN) and folder.created_by_id != current.id:
        raise _forbidden()
    data = payload.model_dump(exclude_unset=True)
    if "parent_id" in data and data["parent_id"] is not None:
        new_parent = data["parent_id"]
        if new_parent == folder_id:
            raise HTTPException(400, detail={"code": "INVALID_MOVE", "message": "폴더를 자기 자신 안으로 옮길 수 없습니다"})
        if await db.get(Folder, new_parent) is None:
            raise HTTPException(400, detail={"code": "FOLDER_NOT_FOUND", "message": "옮길 대상 폴더가 존재하지 않습니다"})
        if new_parent in await _descendant_folder_ids(db, folder_id):
            raise HTTPException(400, detail={"code": "INVALID_MOVE", "message": "폴더를 자기 하위로 옮길 수 없습니다"})
    for key, value in data.items():
        setattr(folder, key, value)
    await db.commit()
    await db.refresh(folder)
    return folder


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    folder = await db.get(Folder, folder_id)
    if folder is None:
        raise HTTPException(404, detail={"code": "FOLDER_NOT_FOUND", "message": "폴더를 찾을 수 없습니다"})
    _ensure_mine(folder.scope, folder.created_by_id, current)
    if current.role not in (Role.MASTER, Role.ADMIN) and folder.created_by_id != current.id:
        raise _forbidden()
    # 서브트리 전체(자신 + 하위 폴더) — 문서·즐겨찾기·폴더 순으로 정리
    ids = list(await _descendant_folder_ids(db, folder_id) | {folder_id})
    docs = (await db.execute(select(Document).where(Document.folder_id.in_(ids)))).scalars().all()
    for d in docs:
        path = d.url.lstrip("/")
        if os.path.exists(path):
            os.remove(path)
    if docs:
        doc_ids = [d.id for d in docs]
        await db.execute(delete(DocumentFavorite).where(DocumentFavorite.document_id.in_(doc_ids)))
    await db.execute(delete(Document).where(Document.folder_id.in_(ids)))
    await db.execute(delete(Folder).where(Folder.id.in_(ids)))
    await db.commit()
    return None


# ---------- Document ----------
@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    space: str | None = Query(None),
    scope: str | None = Query(None),
    folder_id: str | None = Query(None, alias="folderId"),
    favorite: bool = Query(False),  # true → 내 즐겨찾기만
    q: str | None = Query(None),
) -> list[DocumentOut]:
    stmt = select(Document)
    if space:
        stmt = stmt.where(Document.space == space)
    if scope:
        stmt = stmt.where(Document.scope == scope)
    stmt = _mine_only(stmt, Document.scope, Document.uploader_id, current)
    if folder_id:
        stmt = stmt.where(Document.folder_id == folder_id)
    if favorite:
        stmt = stmt.where(
            Document.id.in_(
                select(DocumentFavorite.document_id).where(
                    DocumentFavorite.employee_id == current.id
                )
            )
        )
    if q:
        stmt = stmt.where(or_(Document.name.ilike(f"%{q}%"), Document.desc.ilike(f"%{q}%")))
    result = await db.execute(stmt.order_by(Document.created_at.desc()))
    return await _docs_out(db, list(result.scalars().all()), current)


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    scope: str = Form(...),
    space: str = Form(...),
    folder_id: str | None = Form(None, alias="folderId"),
    name: str | None = Form(None),
    desc: str | None = Form(None),
    tags: str | None = Form(None),
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    if folder_id and await db.get(Folder, folder_id) is None:
        raise HTTPException(400, detail={"code": "FOLDER_NOT_FOUND", "message": "폴더가 존재하지 않습니다"})
    url, ext, size = await save_upload(file)
    document = Document(
        name=name or (file.filename or "file"),
        ext=ext,
        size_bytes=size,
        url=url,
        scope=scope,
        space=space,
        folder_id=folder_id,
        tags=_parse_tags(tags),
        desc=desc,
        uploader_id=current.id,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return (await _docs_out(db, [document], current))[0]


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def update_document(
    document_id: str,
    payload: DocumentUpdate,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "문서를 찾을 수 없습니다"})
    _ensure_mine(document.scope, document.uploader_id, current)
    if current.role not in (Role.MASTER, Role.ADMIN) and document.uploader_id != current.id:
        raise _forbidden()
    data = payload.model_dump(exclude_unset=True)
    if data.get("folder_id") is not None and await db.get(Folder, data["folder_id"]) is None:
        raise HTTPException(400, detail={"code": "FOLDER_NOT_FOUND", "message": "옮길 대상 폴더가 존재하지 않습니다"})
    for key, value in data.items():
        setattr(document, key, value)
    await db.commit()
    await db.refresh(document)
    return (await _docs_out(db, [document], current))[0]


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "문서를 찾을 수 없습니다"})
    _ensure_mine(document.scope, document.uploader_id, current)
    if current.role not in (Role.MASTER, Role.ADMIN) and document.uploader_id != current.id:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "업로더 또는 관리자만 삭제할 수 있습니다"})
    path = document.url.lstrip("/")
    if os.path.exists(path):
        os.remove(path)
    await db.execute(delete(DocumentFavorite).where(DocumentFavorite.document_id == document_id))
    await db.delete(document)
    await db.commit()
    return None


@router.post("/documents/{document_id}/favorite", status_code=204)
async def add_favorite(
    document_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """즐겨찾기 등록 (멱등). 공지 읽음과 같은 방식."""
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "문서를 찾을 수 없습니다"})
    _ensure_mine(document.scope, document.uploader_id, current)
    exists = (
        await db.execute(
            select(DocumentFavorite).where(
                DocumentFavorite.document_id == document_id,
                DocumentFavorite.employee_id == current.id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(DocumentFavorite(document_id=document_id, employee_id=current.id))
        await db.commit()
    return None


@router.delete("/documents/{document_id}/favorite", status_code=204)
async def remove_favorite(
    document_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        delete(DocumentFavorite).where(
            DocumentFavorite.document_id == document_id,
            DocumentFavorite.employee_id == current.id,
        )
    )
    await db.commit()
    return None


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: str,
    current: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "문서를 찾을 수 없습니다"})
    _ensure_mine(document.scope, document.uploader_id, current)
    path = document.url.lstrip("/")
    if not os.path.exists(path):
        raise HTTPException(404, detail={"code": "FILE_MISSING", "message": "파일이 존재하지 않습니다"})
    download_name = document.name if document.name.endswith(f".{document.ext}") else f"{document.name}.{document.ext}"
    return FileResponse(path, filename=download_name)
