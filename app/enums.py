"""도메인 enum — 권한(Role) ≠ 직급(Rank) (CLAUDE.md §1, §2.2)."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    MEMBER = "MEMBER"


class Rank(StrEnum):
    JUNIOR_TRAINER = "JUNIOR_TRAINER"
    PRO_TRAINER = "PRO_TRAINER"
    PRO1_TRAINER = "PRO1_TRAINER"
    TEAM_LEAD = "TEAM_LEAD"
    STORE_MANAGER = "STORE_MANAGER"
    FC = "FC"


class EmployeeStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    RESIGNED = "RESIGNED"


class WorkStatus(StrEnum):
    AUTO = "AUTO"
    MEETING = "MEETING"
    MEAL = "MEAL"
    OUT = "OUT"
    AWAY = "AWAY"


class InviteStatus(StrEnum):
    UNUSED = "UNUSED"
    USED = "USED"
    EXPIRED = "EXPIRED"


class JoinRequestStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
