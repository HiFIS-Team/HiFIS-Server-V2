"""Payslip DTO — CLAUDE.md §5."""

from datetime import datetime

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


class PayslipBasis(CamelModel):
    new_sales: list[SaleItem]
    renewal_sales: list[SaleItem]
    session_signs: int


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
