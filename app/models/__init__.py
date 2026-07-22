"""모델 등록 지점 — Alembic autogenerate 가 metadata 를 인식하도록 여기서 import."""

from app.models.branch import Branch
from app.models.employee import Employee
from app.models.env import EnvItem, EnvTaskLog, SupplyOrder
from app.models.invite import InviteKey
from app.models.join_request import JoinRequest
from app.models.member import Member
from app.models.registration import Registration
from app.models.score_event import ScoreEvent
from app.models.session_sign import SessionSign

__all__ = [
    "Branch",
    "Employee",
    "EnvItem",
    "EnvTaskLog",
    "SupplyOrder",
    "InviteKey",
    "JoinRequest",
    "Member",
    "Registration",
    "ScoreEvent",
    "SessionSign",
]
