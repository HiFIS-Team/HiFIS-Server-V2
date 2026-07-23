"""문서함 DTO — CLAUDE.md §6.6. (업로드는 멀티파트 폼이라 별도 스키마 없음)"""

from app.schemas.base import CamelModel


class FolderCreate(CamelModel):
    name: str
    scope: str
    space: str
    parent_id: str | None = None


class FolderUpdate(CamelModel):
    name: str | None = None


class FolderOut(CamelModel):
    id: str
    name: str
    scope: str
    space: str
    parent_id: str | None = None
    created_by_id: str


class DocumentUpdate(CamelModel):
    name: str | None = None
    desc: str | None = None


class DocumentOut(CamelModel):
    id: str
    name: str
    ext: str
    size_bytes: int
    url: str
    scope: str
    space: str
    folder_id: str | None = None
    tags: list[str]
    desc: str | None = None
    uploader_id: str
