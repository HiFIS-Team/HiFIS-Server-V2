"""도메인 enum — 권한(Role) ≠ 직급(Rank) (CLAUDE.md §1, §2.2)."""

from enum import StrEnum


class Role(StrEnum):
    MASTER = "MASTER"    # 대표 — 승인·반려 등 최종 결정권 전부
    ADMIN = "ADMIN"      # 관리자 — 전 지점 조회(마스터와 같은 화면)이나 승인·반려는 불가(보기만)
    MANAGER = "MANAGER"
    MEMBER = "MEMBER"


class Rank(StrEnum):
    TRAINER = "TRAINER"              # 트레이너 (권한 MEMBER)
    FC = "FC"                        # FC 정규 (권한 MEMBER)
    TEAM_LEAD = "TEAM_LEAD"          # 팀장 (권한 MANAGER)
    STORE_MANAGER = "STORE_MANAGER"  # 점장 (권한 MANAGER)
    DEVELOPER = "DEVELOPER"          # 개발자 (권한 MASTER)
    CEO = "CEO"                      # 대표 (권한 MASTER)


def role_for_rank(rank: "Rank") -> "Role":
    """직급 → 권한 매핑. FC·트레이너=MEMBER / 팀장·점장=MANAGER / 개발자·대표=MASTER.

    ※ ADMIN(전 지점 조회 전용 참관 권한)은 어느 직급에도 자동 매핑되지 않는다 —
      대표(MASTER)가 직원 수정에서 수동 지정한다.
    """
    if rank in (Rank.DEVELOPER, Rank.CEO):
        return Role.MASTER
    if rank in (Rank.TEAM_LEAD, Rank.STORE_MANAGER):
        return Role.MANAGER
    return Role.MEMBER


# 권한 위계 — 승인·감사·수정 가드에서 "이 권한 이상인가" 판단에 사용.
_ROLE_ORDER: dict[Role, int] = {Role.MEMBER: 0, Role.MANAGER: 1, Role.ADMIN: 2, Role.MASTER: 3}


def role_at_least(role: "Role", floor: "Role") -> bool:
    """권한 위계 비교 — role 이 floor 이상인지. MASTER > ADMIN > MANAGER > MEMBER."""
    return _ROLE_ORDER[role] >= _ROLE_ORDER[floor]


class PayslipStatus(StrEnum):
    DRAFT = "DRAFT"          # 미제출(계산됨)
    SUBMITTED = "SUBMITTED"  # 제출(대표자 승인 대기)
    APPROVED = "APPROVED"    # 승인 완료(지급 확정)
    REJECTED = "REJECTED"    # 반려


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


class ProjectRequestType(StrEnum):
    """프로젝트 기한 변경 요청 종류 (매니저·멤버 → 어드민 승인)."""

    EXTENSION = "EXTENSION"  # 기한 연장 요청 (마감 전)
    OVERDUE = "OVERDUE"      # 누락 사유 (마감 지남 — 왜 늦었고 언제까지 끝내겠다)


class ProjectRequestStatus(StrEnum):
    PENDING = "PENDING"      # 대기 (어드민 승인 전)
    APPROVED = "APPROVED"    # 승인 (새 기한 반영)
    REJECTED = "REJECTED"    # 반려 (사유 필수)


class MeetingScope(StrEnum):
    COMPANY = "COMPANY"
    PROJECT = "PROJECT"
    PEOPLE = "PEOPLE"


class AttendanceSource(StrEnum):
    BARCODE = "BARCODE"
    MANUAL = "MANUAL"


class AttendanceStatus(StrEnum):
    """근태 기록 판정 (서버 계산, §6.9) — 기록이 있는 날만. 결근/월차/휴무는 근무일·휴가로 별도 판단."""

    NORMAL = "NORMAL"                  # 정상
    LATE = "LATE"                      # 지각
    EARLY_LEAVE = "EARLY_LEAVE"        # 조기퇴근
    LATE_AND_EARLY = "LATE_AND_EARLY"  # 지각 + 조기퇴근
    IN_PROGRESS = "IN_PROGRESS"        # 출근했고 아직 퇴근 전(당일)
    NO_CHECKOUT = "NO_CHECKOUT"        # 지난 날인데 퇴근 기록 없음
    UNKNOWN = "UNKNOWN"                # 근무시간 미설정 등 판정 불가


class LeaveType(StrEnum):
    ANNUAL = "ANNUAL"  # 연차
    HALF = "HALF"      # 반차
    SICK = "SICK"      # 병가
    FIELD = "FIELD"    # 외근
    ETC = "ETC"


class HalfPeriod(StrEnum):
    """반차 시간대 — type=HALF 일 때만 의미 있음 (오전/오후)."""

    AM = "AM"  # 오전 반차
    PM = "PM"  # 오후 반차


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
    PROJECT = "PROJECT"    # 프로젝트 달성 (기본 10, 어드민 평가 -100 ~ +100)
    OPERATOR = "OPERATOR"  # 운영자 직접 부여/감점


class RankingKind(StrEnum):
    """랭킹 탭 종류 — /scores/ranking?kind=. 표시 순서: 종합왕 → 매출왕 → 수업왕 → 친절왕 → 피드백왕."""

    OVERALL = "OVERALL"    # 종합왕 — 전체 점수 합
    SALES = "SALES"        # 매출왕 — 매출성과(SALES) 자동 기여도 (CONTRIB 중 sales:*)
    CLASS = "CLASS"        # 수업왕 — 수업 개수 점수
    KINDNESS = "KINDNESS"  # 친절왕 — 회원 친절도
    PEER = "PEER"          # 피드백왕 — 동료평가


class ReactionTargetType(StrEnum):
    NOTICE = "NOTICE"    # 공지
    MEETING = "MEETING"  # 회의록
    MESSAGE = "MESSAGE"  # 사내톡 메시지 (§6.11, 추후)


class AccessEvent(StrEnum):
    """접속 로그 이벤트 — 개인정보처리방침 §1-1·§8(접속 기록 보관)."""

    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAIL = "LOGIN_FAIL"
