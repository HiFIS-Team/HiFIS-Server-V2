"""모델 등록 지점 — Alembic autogenerate 가 metadata 를 인식하도록 여기서 import."""

from app.models.platform.account import Account, AccountAccessLog
from app.models.collab.approval import Approval
from app.models.collab.chat import ChatRoom, ChatRoomMember, Message
from app.models.org.attendance import Attendance, LeaveRequest
from app.models.org.branch import Branch
from app.models.scoring.contribution import ContributionGrant
from app.models.platform.document import Document, Folder
from app.models.org.employee import Employee
from app.models.scoring.env import EnvItem, EnvTaskLog, SupplyOrder
from app.models.collab.event import Event
from app.models.org.invite import InviteKey
from app.models.org.join_request import JoinRequest
from app.models.scoring.kindness import KindnessSurvey
from app.models.collab.meeting import Meeting
from app.models.sales.member import Member
from app.models.collab.notice import Notice
from app.models.collab.notification import Notification, PushSubscription
from app.models.payroll.payslip import Payslip
from app.models.scoring.peer_review import PeerReview
from app.models.collab.project import Project
from app.models.payroll.rank_policy import RankPolicy
from app.models.collab.reaction import Reaction
from app.models.sales.registration import Registration
from app.models.scoring.score_event import ScoreEvent
from app.models.sales.session_sign import SessionSign
from app.models.collab.todo import Todo

__all__ = [
    "Account",
    "AccountAccessLog",
    "Approval",
    "ChatRoom",
    "ChatRoomMember",
    "Message",
    "Attendance",
    "LeaveRequest",
    "Branch",
    "ContributionGrant",
    "Document",
    "Folder",
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
    "Notification",
    "PushSubscription",
    "Payslip",
    "PeerReview",
    "Project",
    "RankPolicy",
    "Reaction",
    "Registration",
    "ScoreEvent",
    "SessionSign",
    "Todo",
]
