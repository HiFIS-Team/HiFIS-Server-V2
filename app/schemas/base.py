"""공통 Pydantic 베이스 — wire(JSON)=camelCase / DB=snake_case (CLAUDE.md §0, §8)."""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.core.file_signing import sign_upload_url

# 업로드 경로(/uploads/..)를 응답 직렬화 시 서명 URL(/files/..?exp&sig)로 자동 변환(§H2)
SignedUrl = Annotated[str, AfterValidator(sign_upload_url)]
SignedUrlOptional = Annotated[str | None, AfterValidator(sign_upload_url)]


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
