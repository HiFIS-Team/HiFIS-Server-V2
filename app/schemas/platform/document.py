"""문서함 DTO — CLAUDE.md §6.6. (업로드는 멀티파트 폼이라 별도 스키마 없음)"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.base import CamelModel, SignedUrl


class FolderCreate(CamelModel):
    name: str
    scope: str
    space: str
    parent_id: str | None = None


class FolderUpdate(CamelModel):
    name: str | None = None
    parent_id: str | None = None  # 이동 — 다른 폴더 하위로. 순환(자기·하위로 이동) 금지


class FolderOut(CamelModel):
    id: str
    name: str
    scope: str
    space: str
    parent_id: str | None = None
    created_by_id: str
    created_at: datetime
    updated_at: datetime


class DocumentUpdate(CamelModel):
    name: str | None = None
    desc: str | None = None
    folder_id: str | None = None  # 이동 — 다른 폴더로 (null=최상위)


class DocumentOut(CamelModel):
    id: str
    name: str
    ext: str
    size_bytes: int
    url: SignedUrl
    scope: str
    space: str
    folder_id: str | None = None
    tags: list[str]
    desc: str | None = None
    uploader_id: str
    created_at: datetime
    updated_at: datetime
    favorited_by_me: bool = False  # 내 즐겨찾기 여부 (§6.6)


# ---------- 폴더째 업로드 (원자적 폴더 트리 생성, §6.6) ----------
class FolderTreeNode(CamelModel):
    """업로드할 폴더 하나 + 하위 폴더(재귀)."""

    name: str
    children: list[FolderTreeNode] = Field(default_factory=list)


class FolderTreeCreate(CamelModel):
    scope: str
    space: str
    parent_id: str | None = None  # 트리를 붙일 위치 (null=최상위)
    nodes: list[FolderTreeNode]


class FolderTreeNodeOut(CamelModel):
    """생성된 폴더 — 새 id + 하위(입력 구조 그대로). 앱이 로컬 경로↔id 매핑."""

    id: str
    name: str
    children: list[FolderTreeNodeOut] = Field(default_factory=list)


FolderTreeNode.model_rebuild()
FolderTreeNodeOut.model_rebuild()
