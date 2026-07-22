"""모델 등록 지점 — Alembic autogenerate 가 metadata 를 인식하도록 여기서 import."""

from app.models.branch import Branch
from app.models.employee import Employee
from app.models.invite import InviteKey
from app.models.join_request import JoinRequest
from app.models.member import Member
from app.models.registration import Registration

__all__ = ["Branch", "Employee", "InviteKey", "JoinRequest", "Member", "Registration"]
