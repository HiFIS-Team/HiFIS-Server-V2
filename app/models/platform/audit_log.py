"""활동 로그 — 누가 무엇을 바꿨는지 (개인정보처리방침 §1-1·§3·§8).

접속 로그(`access_logs`)가 '들어왔다/못 들어왔다'만 남긴다면 이쪽은 **한 일**을 남긴다.
쓰기 요청(POST·PATCH·PUT·DELETE)이 지나갈 때 미들웨어가 한 줄씩 적는다.

`payload` 에 보낸 내용이 그대로 들어간다 — 공지를 뭐라고 썼는지, 누구 권한을
무엇으로 바꿨는지가 글자 그대로 남는다. 비밀번호·토큰·인증번호는 마스킹한다.

보존기간은 접속 로그와 같다(access_log_retention_days, 기본 90일) — retention 잡이 파기.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDMixin


class AuditLog(UUIDMixin, Base):
    __tablename__ = "audit_logs"

    # 직원 소프트삭제(탈퇴)여도 유지 → 하드삭제 시엔 NULL 로 이력 보존
    employee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    method: Mapped[str] = mapped_column(String(10), nullable=False)

    # 실제로 부른 주소 — id 가 들어 있어 어느 문서인지 되짚을 수 있다
    path: Mapped[str] = mapped_column(String(500), nullable=False)

    # id 를 {id} 로 바꾼 모양 — 한국어 라벨을 붙이는 키이자 묶어 세는 기준
    route: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    # 응답 코드 — 실패한 시도(403·400)가 오히려 봐야 할 값이다
    status: Mapped[int] = mapped_column(Integer, nullable=False)

    # 보낸 내용. 파일 업로드·너무 큰 본문은 안 담는다(사유만 남긴다)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6 최대 45자
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # 파기(범위 삭제)·정렬 조회 모두 created_at 기준 → 인덱스
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
