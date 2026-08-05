"""Payslip DTO — CLAUDE.md §5."""

from datetime import date, datetime

from pydantic import computed_field

from app.enums import DeductionMethod, PayslipStatus, Rank
from app.schemas.base import CamelModel


class PayslipGenerateRequest(CamelModel):
    branch_id: str
    year_month: str


class PayslipSubmit(CamelModel):
    year_month: str
    note: str | None = None  # 특이사항(선택) — 지각 사유·추가 근무 설명 등


class PayslipReject(CamelModel):
    reason: str


class PaydayWindowOut(CamelModel):
    year_month: str
    payday: str  # "YYYY-MM-DD"
    is_open: bool


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

    @computed_field
    @property
    def payday(self) -> date:
        """지급 예정일 — `year_month` 에서 나온다 (지금은 전 지점 말일).

        결재하는 쪽이 "언제 나갈 돈인지"를 보고 승인하므로 명세서마다 싣는다.
        앱이 규칙을 따로 들고 있으면 여기가 바뀔 때 어긋난다 (실제로 앱
        폴백이 '익월 10일' 로 잘못 박혀 있었다).
        """
        from app.services.payroll import compute_payday

        return compute_payday(self.year_month)
