"""공통 Pydantic 베이스 — wire(JSON)=camelCase / DB=snake_case (CLAUDE.md §0, §8)."""

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.core.file_signing import sign_upload_url


def normalize_phone(v: str) -> str:
    """휴대폰 번호 — 숫자만 남겨 10~11자리 검증(프론트 auth_signup.dart 와 동일 규칙)."""
    digits = re.sub(r"\D", "", v or "")
    if len(digits) not in (10, 11):
        raise ValueError("전화번호는 숫자 10~11자리여야 합니다")
    return digits

# 업로드 경로(/uploads/..)를 응답 직렬화 시 서명 URL(/files/..?exp&sig)로 자동 변환(§H2)
SignedUrl = Annotated[str, AfterValidator(sign_upload_url)]
SignedUrlOptional = Annotated[str | None, AfterValidator(sign_upload_url)]


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
