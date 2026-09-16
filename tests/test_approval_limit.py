"""전자결재 금액 문턱 — **10만원부터 대표 승인** (2026-09-16 대표 결정).

그 아래는 올리는 즉시 승인으로 선다. 소모품 사는 데까지 대표를 거치면
결재함이 잔건으로 차서 정작 봐야 할 것이 묻힌다.

**대표·관리자는 금액을 안 본다.** 판단하는 쪽이라 자기가 올린 것을 자기가
승인하는 자리가 되는데, 그건 결재가 아니라 절차만 한 번 더 도는 것이다.

깨지면 고치기 전에 **의도한 변경인지 먼저 확인한다** — 돈이 대표를 안 거치고
나가는 쪽으로 바뀌면 안 된다.
"""

import pytest

from app.api.board.approvals import APPROVAL_LIMIT, _needs_approval
from app.enums import Role
from app.models.staff.employee import Employee


def _who(role: Role) -> Employee:
    return Employee(role=role)


@pytest.mark.parametrize("role", [Role.MEMBER, Role.MANAGER])
def test_직원_점장은_문턱부터_승인을_받는다(role: Role):
    person = _who(role)
    assert _needs_approval(person, APPROVAL_LIMIT - 1) is False
    # **딱 10만원은 받는다** — `이상` 이 승인이다
    assert _needs_approval(person, APPROVAL_LIMIT) is True
    assert _needs_approval(person, APPROVAL_LIMIT * 3) is True


@pytest.mark.parametrize("role", [Role.MASTER, Role.ADMIN])
def test_대표_관리자는_금액을_안_본다(role: Role):
    person = _who(role)
    assert _needs_approval(person, APPROVAL_LIMIT * 100) is False


@pytest.mark.parametrize("role", list(Role))
def test_금액이_없으면_결재를_안_탄다(role: Role):
    """외근·근무 변경처럼 돈이 안 드는 갈래 — `None` 은 0으로 본다."""
    assert _needs_approval(_who(role), None) is False
    assert _needs_approval(_who(role), 0) is False
