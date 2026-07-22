"""모델 등록 지점 — Alembic autogenerate 가 metadata 를 인식하도록 여기서 import."""

from app.models.account import Account, AccountAccessLog
from app.models.approval import Approval
from app.models.attendance import Attendance, LeaveRequest
from app.models.branch import Branch
from app.models.contribution import ContributionGrant
from app.models.employee import Employee
from app.models.env import EnvItem, EnvTaskLog, SupplyOrder
from app.models.event import Event
from app.models.invite import InviteKey
from app.models.join_request import JoinRequest
from app.models.kindness import KindnessSurvey
from app.models.meeting import Meeting
from app.models.member import Member
from app.models.notice import Notice
from app.models.payslip import Payslip
from app.models.peer_review import PeerReview
from app.models.project import Project
from app.models.rank_policy import RankPolicy
from app.models.registration import Registration
from app.models.score_event import ScoreEvent
from app.models.session_sign import SessionSign
from app.models.todo import Todo

__all__ = [
    "Account",
    "AccountAccessLog",
    "Approval",
    "Attendance",
    "LeaveRequest",
    "Branch",
    "ContributionGrant",
    "Employee",
    "EnvItem",
    "EnvTaskLog",
    "SupplyOrder",
    "Event",
    "InviteKey",
    "JoinRequest",
    "KindnessSurvey",
    "Meeting",
    "Member",
    "Notice",
    "Payslip",
    "PeerReview",
    "Project",
    "RankPolicy",
    "Registration",
    "ScoreEvent",
    "SessionSign",
    "Todo",
]
