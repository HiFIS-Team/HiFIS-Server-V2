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
    MARKETER = "MARKETER"            # 마케터 (권한 MEMBER)
    TEAM_LEAD = "TEAM_LEAD"          # 팀장 (권한 MANAGER)
    STORE_MANAGER = "STORE_MANAGER"  # 점장 (권한 MANAGER)
    DEVELOPER = "DEVELOPER"          # 개발자 (권한 MASTER)
    CEO = "CEO"                      # 대표 (권한 MASTER)


def role_for_rank(rank: "Rank") -> "Role":
    """직급 → 권한 매핑. 트레이너·FC·마케터=MEMBER / 팀장·점장=MANAGER / 개발자·대표=MASTER.

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
    APPROVED = "APPROVED"    # 승인 완료(지급 확정 — 아직 입금 전)
    PAID = "PAID"            # 지급 완료(실입금 확인)
    REJECTED = "REJECTED"    # 반려


class EmploymentType(StrEnum):
    """고용 형태 — 재직 상태(EmployeeStatus)와 **다른 축**이다.

    알바가 그만두면 `status=RESIGNED` 로 가고 고용 형태는 그대로 남는다.
    한 사람이 알바로 시작해 정규직이 되는 경우도 이 값만 바꾸면 된다.
    """

    FULL_TIME = "FULL_TIME"  # 정규직 — 직급별 기본급 + 인센티브
    PART_TIME = "PART_TIME"  # 알바 — 시급제만 (직급과 무관하게 인센티브 없음)


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
    """프로젝트 결재 요청 종류 (담당자·참여 멤버 → MASTER 승인).

    **EDIT·DELETE 는 2026-08-14 에 붙었다.** "수정 및 삭제는 마스터의 허가가
    있어야 가능하다" — 그 전에는 담당자가 그냥 고치고 그냥 지웠다.
    기한 연장이 이미 쓰던 통로를 그대로 탄다.
    """

    EXTENSION = "EXTENSION"  # 기한 연장 요청 (마감 전) — new_due 필수
    OVERDUE = "OVERDUE"      # 누락 사유 (마감 지남 — 왜 늦었고 언제까지 끝내겠다) — new_due 필수
    EDIT = "EDIT"            # 이름·설명·색 수정 — payload 필수
    DELETE = "DELETE"        # 프로젝트 삭제 — 둘 다 없음


class ProjectRequestStatus(StrEnum):
    PENDING = "PENDING"      # 대기 (어드민 승인 전)
    APPROVED = "APPROVED"    # 승인 (새 기한 반영)
    REJECTED = "REJECTED"    # 반려 (사유 필수)


class ProjectActivityKind(StrEnum):
    """프로젝트 상세 타임라인 항목 종류. COMMENT=사용자 댓글 / 나머지=시스템 활동 기록.
    native_enum=False(VARCHAR)라 종류 추가 시 마이그레이션 불필요."""

    COMMENT = "COMMENT"      # 사용자가 쓴 댓글 (body 필수, 수정·삭제 가능)
    CREATED = "CREATED"      # 프로젝트 생성
    PROGRESS = "PROGRESS"    # 진행률 변경(수동)
    TODO = "TODO"            # 체크리스트 완료
    DUE = "DUE"              # 기한 변경(수정·연장 승인)
    ASSIGNEE = "ASSIGNEE"    # 담당자 변경


class MeetingScope(StrEnum):
    COMPANY = "COMPANY"
    PROJECT = "PROJECT"
    PEOPLE = "PEOPLE"


class AttendanceSource(StrEnum):
    BARCODE = "BARCODE"
    MANUAL = "MANUAL"


class AttendanceStatus(StrEnum):
    """근태 판정 (서버 계산, §6.9). NORMAL~NO_CHECKOUT 은 기록 기반, ABSENT~DAY_OFF 는 일자 기반(캘린더)."""

    NORMAL = "NORMAL"                  # 정상
    LATE = "LATE"                      # 지각
    EARLY_LEAVE = "EARLY_LEAVE"        # 조기퇴근
    LATE_AND_EARLY = "LATE_AND_EARLY"  # 지각 + 조기퇴근
    OVERTIME = "OVERTIME"              # 야근 — 퇴근 스캔이 설정 퇴근시간보다 1시간+ 늦음
    IN_PROGRESS = "IN_PROGRESS"        # 출근했고 아직 퇴근 전(당일)
    NO_CHECKOUT = "NO_CHECKOUT"        # 지난 날인데 퇴근 기록 없음
    ABSENT = "ABSENT"                  # 결근 — 근무일인데 과거·기록 없음·휴가 없음
    ON_LEAVE = "ON_LEAVE"              # 휴가/월차(승인) — 반차 포함
    DAY_OFF = "DAY_OFF"                # 휴무 — 근무 요일 아님
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


class ComplaintStatus(StrEnum):
    """친절 설문의 '개선했으면 하는 부분' 처리 단계 (§4.5).

    설문에 개선 의견이 적혀 있으면 그게 컴플레인이다. 해결하면 DONE 이 되고,
    매장 TV 화면이 그것만 골라 '해결 완료' 로 띄운다.
    """

    PENDING = "PENDING"  # 미처리
    WORKING = "WORKING"  # 해결중
    DONE = "DONE"        # 해결 완료


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


class VisitPath(StrEnum):
    """회원이 어떻게 알고 왔나 — 회원 등록 때 받는다 (§3.1).

    **뒤 셋만 점수를 준다** (`VISIT_PATH_SCORE`). 워크인·지인소개는 직원이
    끌어온 것이 아니라서 뺀다.
    """

    WALK_IN = "WALK_IN"      # 워크인 — 점수 없음
    REFERRAL = "REFERRAL"    # 지인소개 — 점수 없음
    BLOG = "BLOG"            # 블로그
    INSTAGRAM = "INSTAGRAM"  # 인스타
    OT_TO_PT = "OT_TO_PT"    # OT → PT 전환


class ScoreCategory(StrEnum):
    ENV = "ENV"            # 환경정비
    PEER = "PEER"          # 동료평가
    KINDNESS = "KINDNESS"  # 회원 친절도
    CLASS = "CLASS"        # 수업 개수
    CONTRIB = "CONTRIB"    # 센터 기여도
    PROJECT = "PROJECT"    # 프로젝트 달성 (기본 10, 어드민 평가 -100 ~ +100)
    OPERATOR = "OPERATOR"  # 운영자 직접 부여/감점
    # 방문 경로 — 셋을 **따로** 둔다. 랭킹 내역이 '블로그 10 · 인스타 5' 처럼
    # 갈라서 보여줘야 해서 하나로 묶으면 다시 못 나눈다.
    BLOG = "BLOG"              # 블로그 보고 온 회원 등록
    INSTAGRAM = "INSTAGRAM"    # 인스타 보고 온 회원 등록
    OT_PT = "OT_PT"            # OT → PT 전환


#: 방문 경로 → 담당 트레이너에게 붙는 점수 (없으면 안 준다)
VISIT_PATH_SCORE: dict[VisitPath, tuple[ScoreCategory, int]] = {
    VisitPath.BLOG: (ScoreCategory.BLOG, 5),
    VisitPath.INSTAGRAM: (ScoreCategory.INSTAGRAM, 5),
    VisitPath.OT_TO_PT: (ScoreCategory.OT_PT, 5),
}


class RankingKind(StrEnum):
    """랭킹 탭 종류 — /scores/ranking?kind=. 헤드라인 순서: 종합왕 → 매출왕 → 수업왕 → 친절왕 → 피드백왕.

    PROJECT·ENV 는 앱에서 on-demand 조회용(kind 값 = ScoreCategory 동명 → kind_conditions 자동 매핑).
    """

    OVERALL = "OVERALL"    # 종합왕 — 전체 점수 합
    SALES = "SALES"        # 매출왕 — 매출성과(SALES) 자동 기여도 (CONTRIB 중 sales:*)
    CLASS = "CLASS"        # 수업왕 — 수업 개수 점수
    KINDNESS = "KINDNESS"  # 친절왕 — 회원 친절도
    PEER = "PEER"          # 피드백왕 — 동료평가
    PROJECT = "PROJECT"    # 프로젝트왕 — 프로젝트 달성 점수 (ScoreCategory.PROJECT)
    ENV = "ENV"            # 환경왕 — 환경정비 점수 (ScoreCategory.ENV)


class ReactionTargetType(StrEnum):
    NOTICE = "NOTICE"    # 공지
    MEETING = "MEETING"  # 회의록
    MESSAGE = "MESSAGE"  # 사내톡 메시지 (§6.11, 추후)


class MessageKind(StrEnum):
    """사내톡 메시지 종류 — 사람이 쓴 것과 서버가 남긴 안내를 가른다.

    SYSTEM 은 앱이 말풍선이 아니라 가운데 회색 한 줄로 그린다
    (초대·나가기·이름 변경).
    """

    TEXT = "TEXT"
    SYSTEM = "SYSTEM"


class EventStatus(StrEnum):
    """일정 승인 상태.

    MASTER·ADMIN 이 올린 것은 바로 APPROVED, 나머지는 PENDING 으로 들어간다.

    **반려해도 행을 남긴다 (2026-08-14).** 예전에는 지웠는데, 그러면 급여·월차·
    전자결재는 다 남는 반려 이력이 **일정만 없었다**. 대신 `GET /events` 가
    REJECTED 를 빼서 달력에는 안 뜬다 — 죽은 일정이 칸을 어지럽히지 않는 것은
    그대로다.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InboxKind(StrEnum):
    """홈 결재함 한 줄의 출처 — 승인·반려를 어느 엔드포인트로 보낼지 가른다."""

    PAYSLIP = "PAYSLIP"    # POST /payslips/{id}/approve|reject
    LEAVE = "LEAVE"        # POST /leaves/{id}/approve|reject
    APPROVAL = "APPROVAL"  # POST /approvals/{id}/approve|reject
    EVENT = "EVENT"        # POST /events/{id}/approve|reject


class InboxStatus(StrEnum):
    """홈 결재함이 어느 칸을 보여줄지 — 앱의 `대기 · 승인 · 반려` 탭.

    네 테이블의 상태 이름이 제각각이라(급여 SUBMITTED, 전자결재 IN_PROGRESS …)
    앱이 종류별로 물어보면 분기만 는다. **이 셋으로만 묻고** 어느 상태가
    거기 속하는지는 서버가 안다.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"  # 본인이 물린 것(월차 취소·결재 회수)도 여기 들어간다


class AccessEvent(StrEnum):
    """접속 로그 이벤트 — 개인정보처리방침 §1-1·§8(접속 기록 보관)."""

    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAIL = "LOGIN_FAIL"


class AnomalyKind(StrEnum):
    """이상행동 종류 — 접속·활동 로그를 5분마다 훑어 찾는다 (모니터링 '이상 징후')."""

    BRUTE_FORCE = "BRUTE_FORCE"          # 같은 계정·IP 로 로그인 반복 실패
    FORBIDDEN_BURST = "FORBIDDEN_BURST"  # 권한 없는 요청 반복 — 앱에 없는 걸 직접 부름
    NEW_DEVICE = "NEW_DEVICE"            # 그 사람이 안 쓰던 IP·기기에서 로그인
    BULK_DELETE = "BULK_DELETE"          # 짧은 시간에 대량 삭제
    READ_BURST = "READ_BURST"            # 남의 대화·기록 열람 급증
    SCREEN_CAPTURE = "SCREEN_CAPTURE"    # 짧은 시간에 화면 캡처 반복 (iOS — 막을 수 없어 세기만 한다)
