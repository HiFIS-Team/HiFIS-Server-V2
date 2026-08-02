"""통합검색 DTO — 사람·공지·회의록·프로젝트·문서 (CLAUDE.md §6.13)."""

from pydantic import Field

from app.schemas.base import CamelModel


class PersonHit(CamelModel):
    id: str
    name: str
    email: str
    team: str | None = None
    avatar_color: str
    branch_id: str


class TitleHit(CamelModel):
    id: str
    title: str


class DocumentHit(CamelModel):
    id: str
    name: str
    ext: str


class SearchResults(CamelModel):
    people: list[PersonHit] = Field(default_factory=list)
    notices: list[TitleHit] = Field(default_factory=list)
    meetings: list[TitleHit] = Field(default_factory=list)
    projects: list[TitleHit] = Field(default_factory=list)
    documents: list[DocumentHit] = Field(default_factory=list)
