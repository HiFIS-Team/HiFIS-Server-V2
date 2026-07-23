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


class AttendanceSource(StrEnum):
    BARCODE = "BARCODE"
    MANUAL = "MANUAL"


class LeaveType(StrEnum):
    ANNUAL = "ANNUAL"  # 연차
    HALF = "HALF"      # 반차
    SICK = "SICK"      # 병가
    FIELD = "FIELD"    # 외근
    ETC = "ETC"


class LeaveStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"  # 신청자 본인이 대기중 취소


class ApprovalStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"  # 신청자 본인이 진행중 회수(이력 보존)


class ApprovalStepStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ContribType(StrEnum):
    IDEA = "IDEA"              # 창의적 아이디어 = 3
    GOAL = "GOAL"              # 자발적 목표 업무 = 10
    EXTRA_WORK = "EXTRA_WORK"  # 근무 외 출근 1시간 이상 = 10(고정)
    SALES = "SALES"            # 매출성과 = 자동(부여 대상 아님)


class ScoreCategory(StrEnum):
    ENV = "ENV"            # 환경정비
    PEER = "PEER"          # 동료평가
    KINDNESS = "KINDNESS"  # 회원 친절도
    CLASS = "CLASS"        # 수업 개수
    CONTRIB = "CONTRIB"    # 센터 기여도
    OPERATOR = "OPERATOR"  # 운영자 직접 부여/감점


class ReactionTargetType(StrEnum):
    NOTICE = "NOTICE"    # 공지
    MEETING = "MEETING"  # 회의록
    MESSAGE = "MESSAGE"  # 사내톡 메시지 (§6.11, 추후)
