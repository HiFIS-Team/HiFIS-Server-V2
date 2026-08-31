"""Payslip DTO — CLAUDE.md §5."""

from datetime import date, datetime

from pydantic import Field, computed_field

from app.enums import DeductionMethod, PayslipStatus, Rank
from app.schemas.base import CamelModel


class PayslipGenerateRequest(CamelModel):
    branch_id: str
    year_month: str


class PayslipSubmit(CamelModel):
    year_month: str
    note: str | None = None  # 특이사항(선택) — 지각 사유·추가 근무 설명 등

    #: 본인이 고친 PT 커미션 — 안 주면 서버 계산값 그대로.
    #:
    #: 자동 집계가 빠뜨린 수업(대타·기록 누락)을 신청 때 바로잡으라고 연다.
    #: **기본급은 못 고친다** — 직급 정책에서 나오는 값이라 본인이 정할 것이 아니다.
    #: 알바(시급제)와 커미션 요율이 0인 직급(FC)은 고칠 자리 자체가 없어 400 이다.
    #: 원래 계산값은 `incentiveNewAuto`·`incentiveRenewalAuto` 로 남아서
    #: 결재하는 쪽이 얼마를 고쳤는지 본다.
    incentive_new: int | None = Field(default=None, ge=0)
    incentive_renewal: int | None = Field(default=None, ge=0)


class PayslipReject(CamelModel):
    reason: str


class PaydayWindowOut(CamelModel):
    year_month: str
    payday: str  # "YYYY-MM-DD"
    is_open: bool


class AccruedOut(CamelModel):
    """진행 중 주기에 **지금까지 쌓인 PT 커미션** — 기본급·공제는 없다.

    확정 명세서는 지급일에 나오지만, 그 전까지 "이번 주기에 얼마 쌓였나"를
    볼 길이 없었다. 세션 싸인을 찍을 때마다 바로 오르는 값이다.
    """

    year_month: str  # 이 주기가 나중에 만들 명세서의 월
    period_start: date
    period_end: date  # 이 날 **전날까지**가 이번 주기다 (end 는 안 포함)
    payday: date
    incentive_new: int  # 워크인 40%
    incentive_renewal: int  # 재등록·지인소개 50%
    total: int  # 둘의 합 — 기본급은 안 들어간다
    session_signs: int
    #: 확정 명세서의 `basis.newSales`·`renewalSales` 길이와 같은 값 —
    #: 화면이 '워크인 N회' 를 붙이는 자리라 진행 중일 때도 있어야 한다
    new_sessions: int
    renewal_sessions: int
    #: 재등록 합이 문턱을 못 넘어 **워크인 요율로 내려갔나** (트레이너만, 2026-08-31).
    #: 화면이 왜 금액이 낮은지 한 줄로 알려 주는 자리다
    renewal_downgraded: bool = False
    #: 신청할 때 본인이 커미션을 고칠 수 있는 사람인가 (알바·FC 는 false).
    #: 앱이 이 값으로 입력칸을 열지 정한다 — 앱이 따로 판정하면 서버와 어긋나
    #: 못 고치는 사람에게 칸이 열리고 제출에서 400 이 난다.
    can_adjust: bool


class DeductionLine(CamelModel):
    label: str
    amount: int


class SaleItem(CamelModel):
    member_name: str
    pkg: str
    amount: int


class HourlyBasis(CamelModel):
    """알바(시급제) 명세서의 근거 — 정규직 명세서에는 없다(null).

    앱은 **이 자리가 채워졌는지**로 시급제 명세서인지를 가른다. 사람의 지금
    고용 형태가 아니라 그 명세서를 뽑을 때 무엇이었는지라, 알바로 일하다
    정규직이 돼도 지난 달 명세서는 시급 그대로 남는다.
    """

    wage: int
    minutes_per_day: int
    work_days: int
    total_minutes: int


class PayslipBasis(CamelModel):
    new_sales: list[SaleItem]
    renewal_sales: list[SaleItem]
    session_signs: int
    hourly: HourlyBasis | None = None


class PayslipOut(CamelModel):
    id: str
    employee_id: str
    year_month: str
    rank: Rank
    base_salary: int
    incentive_new: int
    incentive_renewal: int
    #: 서버가 계산한 원래 커미션 — 위 두 값과 다르면 **본인이 고쳐서 신청한 것**이다.
    #: 결재하는 쪽이 무엇을 승인하는지 알아야 해서 같이 싣는다.
    #: (규칙이 생기기 전 명세서는 null)
    incentive_new_auto: int | None = None
    incentive_renewal_auto: int | None = None
    other_allowances: int
    gross: int
    deduction_method: DeductionMethod
    deductions: list[DeductionLine]
    total_deduction: int
    net: int
    basis: PayslipBasis
    # 제출·결재
    status: PayslipStatus
    note: str | None = None
    reject_reason: str | None = None
    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by_id: str | None = None
    paid_at: datetime | None = None

    #: 만들 때 찍어 둔 지급일 — 화면에는 아래 `payday` 로 나간다
    pay_date: date | None = Field(default=None, exclude=True)

    @computed_field
    @property
    def payday(self) -> date:
        """지급 예정일 — **지점×직급마다 다르다** (화순·FC 말일 / 동광주·첨단 트레이너 익월 10일).

        결재하는 쪽이 "언제 나갈 돈인지"를 보고 승인하므로 명세서마다 싣는다.
        앱이 규칙을 따로 들고 있으면 여기가 바뀔 때 어긋난다 (실제로 앱
        폴백이 '익월 10일' 로 잘못 박혀 있었다).

        규칙이 생기기 전에 만들어진 명세서는 저장된 값이 없어 말일로 떨어진다.
        """
        from app.services.payroll import compute_payday

        return self.pay_date or compute_payday(self.year_month)
