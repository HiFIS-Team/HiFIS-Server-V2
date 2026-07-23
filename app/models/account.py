"""계정 관리 모델 — Account · AccountAccessLog (CLAUDE.md §6.7, §9.6).

비밀번호는 AES-256-GCM 암호문(secret_nonce/secret_ciphertext)으로만 저장. 평문 컬럼 없음.
"""

from sqlalchemy import Boolean, ForeignKey, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class Account(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "accounts"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    cat: Mapped[str] = mapped_column(String(50), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)  # 전사/팀/프로젝트
    login_id: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False, index=True
    )
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    secret_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class AccountAccessLog(UUIDMixin, TimestampMixin, Base):
    """비번 열람 감사 로그 (누가 언제 어떤 계정 비번을 봤는지).

    현재 정책: 계정 삭제 시 이 로그도 함께 삭제(라우터에서 선정리, §6.7).
    escape hatch — "계정은 지워도 열람 이력은 남긴다"가 필요해지면:
      account_id 를 nullable + ForeignKey(..., ondelete="SET NULL") 로 바꾸고
      delete_account 의 로그 선삭제를 제거 → 로그는 account_id=NULL 로 보존.
    """

    __tablename__ = "account_access_logs"

    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=False, index=True
    )
    accessor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("employees.id"), nullable=False
    )
