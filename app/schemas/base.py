"""공통 Pydantic 베이스 — wire(JSON)=camelCase / DB=snake_case (CLAUDE.md §0, §8)."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
