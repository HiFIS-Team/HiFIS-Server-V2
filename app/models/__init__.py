"""모델 등록 지점 — Alembic autogenerate 가 metadata 를 인식하도록 여기서 import."""

from app.models.platform.access_log import AccessLog
from app.models.platform.anomaly import Anomaly
from app.models.platform.api_metric import ApiMetric
from app.models.platform.account import Account, AccountAccessLog
from app.models.platform.audit_log import AuditLog
from app.models.board.approval import Approval
from app.models.chat.chat import ChatRoom, ChatRoomMember, Message
from app.models.staff.attendance import Attendance, LeaveRequest
from app.models.staff.branch import Branch
from app.models.scoring.contribution import ContributionGrant
from app.models.platform.document import Document, Folder
from app.models.staff.employee import Employee
from app.models.scoring.env import EnvItem, EnvTaskLog, SupplyOrder
from app.models.board.event import Event
from app.models.auth.invite import InviteKey
from app.models.scoring.kindness import KindnessSurvey
from app.models.projects.meeting import Meeting
from app.models.members.member import Member
from app.models.board.notice import Notice
from app.models.chat.notification import Notification, PushSubscription
from app.models.payroll.payslip import Payslip
from app.models.scoring.peer_review import PeerReview
from app.models.projects.project import Project
from app.models.projects.project_request import ProjectRequest
from app.models.payroll.hourly_wage import HourlyWagePolicy
from app.models.payroll.payday_policy import PaydayPolicy
from app.models.payroll.rank_policy import RankPolicy
from app.models.scoring.rank_overtake import RankOvertake
from app.models.scoring.ranking_snapshot import RankingSnapshot
from app.models.board.reaction import Reaction
from app.models.members.registration import Registration
from app.models.scoring.score_event import ScoreEvent
from app.models.members.session_sign import SessionSign
from app.models.projects.todo import Todo

__all__ = [
    "Account",
    "AccountAccessLog",
    "Anomaly",
    "ApiMetric",
    "AuditLog",
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
    "KindnessSurvey",
    "Meeting",
    "Member",
    "Notice",
    "Notification",
    "PushSubscription",
    "Payslip",
    "PeerReview",
    "Project",
    "ProjectRequest",
    "HourlyWagePolicy",
    "PaydayPolicy",
    "RankPolicy",
    "RankOvertake",
    "RankingSnapshot",
    "Reaction",
    "Registration",
    "ScoreEvent",
    "SessionSign",
    "Todo",
]
