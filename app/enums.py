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


class RegistrationType(StrEnum):
    NEW = "NEW"          # 신규
    RENEWAL = "RENEWAL"  # 재등록


class RegistrationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"  # usedSessions >= totalSessions


class DeductionMethod(StrEnum):
    FREELANCE = "FREELANCE"  # 사업소득 3.3%
    INSURANCE = "INSURANCE"  # 4대보험


class ProjectStatus(StrEnum):
    WAITING = "WAITING"          # 대기 (progress 0)
    IN_PROGRESS = "IN_PROGRESS"  # 진행중
    DONE = "DONE"                # 완료 (progress ≥ 100)
    MISSED = "MISSED"            # 누락 (마감 지남 + 미완료)


class MeetingScope(StrEnum):
    COMPANY = "COMPANY"
    PROJECT = "PROJECT"
    PEOPLE = "PEOPLE"


class ContribType(StrEnum):
    IDEA = "IDEA"              # 아이디어 = 5
    GOAL = "GOAL"              # 목표달성 = 10
    EXTRA_WORK = "EXTRA_WORK"  # 추가근무 = hours × 3
    SALES = "SALES"            # 매출성과 = 자동(부여 대상 아님)


class ScoreCategory(StrEnum):
    ENV = "ENV"            # 환경정비
    PEER = "PEER"          # 동료평가
    KINDNESS = "KINDNESS"  # 회원 친절도
    CLASS = "CLASS"        # 수업 개수
    CONTRIB = "CONTRIB"    # 센터 기여도
    OPERATOR = "OPERATOR"  # 운영자 직접 부여/감점
