"""모델 등록 지점 — Alembic autogenerate 가 metadata 를 인식하도록 여기서 import."""

from app.models.branch import Branch
from app.models.employee import Employee

__all__ = ["Branch", "Employee"]
