"""동의 이력 DTO — §12 직원 약관 / §13 회원 개인정보."""

from datetime import datetime

from pydantic import Field

from app.schemas.base import CamelModel, SignedUrl


# ---------- 직원 약관 동의 (#12) ----------
class EmployeeConsentCreate(CamelModel):
    doc_type: str = "TERMS"
    doc_version: str = Field(min_length=1)  # 어떤 버전에 동의했는지 필수


class EmployeeConsentOut(CamelModel):
    id: str
    employee_id: str
    doc_type: str
    doc_version: str
    agreed_at: datetime


# ---------- 회원 개인정보 수집 동의 (#13) ----------
class MemberConsentCreate(CamelModel):
    doc_type: str = "PRIVACY"
    doc_version: str = Field(min_length=1)
    signature_base64: str = Field(min_length=1)  # 손님 서명 이미지(base64 PNG)


class MemberConsentOut(CamelModel):
    id: str
    member_id: str
    doc_type: str
    doc_version: str
    signature_url: SignedUrl
    collected_by_id: str
    agreed_at: datetime
