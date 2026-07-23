"""Payslip DTO — CLAUDE.md §5."""

from app.enums import DeductionMethod, Rank
from app.schemas.base import CamelModel


class PayslipGenerateRequest(CamelModel):
    branch_id: str
    year_month: str


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
