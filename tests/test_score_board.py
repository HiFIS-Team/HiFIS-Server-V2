"""센터 기여도 내역에 어느 점수가 서나 (2026-09-16 대표 결정).

**당연한 업무는 안 센다.** 환경정비·수업 싸인·회원 친절도는 하던 일을 한
기록이라 여기 안 서고, 각자 제 화면에 훨씬 자세한 내역이 있다. 9월 운영에서
환경정비만 2,029건이라 같이 세우면 기여 내역이 통째로 덮인다.

깨지면 고치기 전에 **의도한 변경인지 먼저 확인한다** — 사람 점수가 걸린다.
"""

import pytest

from app.api.scoring.scores import (
    _BOARD_CATEGORIES,
    _OFF_BOARD_CATEGORIES,
    _SPLIT_CATEGORIES,
    _contrib_board,
)
from app.enums import ScoreCategory
from app.services.scoring import CLAIM_ITEM_NAME


def test_갈래를_하나도_안_빠뜨린다():
    """**이 테스트가 이 파일의 요점이다.**

    갈래를 새로 만들면서 어느 쪽에 둘지 안 정하면 그 점수는 조용히 안 선다.
    안 서면 되돌릴 수도 없는데, 화면에 아무 표시가 없어서 한참 뒤에나 안다.
    """
    covered = set(_BOARD_CATEGORIES) | set(_OFF_BOARD_CATEGORIES) | set(_SPLIT_CATEGORIES)
    assert covered == set(ScoreCategory)


def test_세_무리가_서로_안_겹친다():
    """한 갈래가 두 무리에 들면 어느 쪽이 이기는지가 읽는 사람마다 달라진다"""
    board, off, split = (set(_BOARD_CATEGORIES), set(_OFF_BOARD_CATEGORIES), set(_SPLIT_CATEGORIES))
    assert board & off == set()
    assert board & split == set()
    assert off & split == set()


@pytest.mark.parametrize(
    "category",
    [ScoreCategory.CLASS, ScoreCategory.KINDNESS, ScoreCategory.PEER],
)
def test_당연한_업무는_안_선다(category: ScoreCategory):
    assert category in _OFF_BOARD_CATEGORIES


@pytest.mark.parametrize(
    "category",
    [
        ScoreCategory.CONTRIB,   # 기여 부여 · 근무 외 출근 · 매출성과
        ScoreCategory.OPERATOR,  # 운영자 직접 부여
        ScoreCategory.BLOG,      # 블로그 보고 온 회원 등록
        ScoreCategory.INSTAGRAM,
        ScoreCategory.OT_PT,     # OT → PT 전환
        ScoreCategory.LATE,      # 아래 셋은 차감
        ScoreCategory.TASK_MISS,
        ScoreCategory.PEER_MISS,
    ],
)
def test_기여로_치는_갈래는_선다(category: ScoreCategory):
    assert category in _BOARD_CATEGORIES


def test_환경정비와_프로젝트는_갈래_안에서_갈린다():
    """둘은 이름만으로 못 정한다.

    - 환경정비: `클레임해결`(컴플레인 해결, 대표 승인)만 서고 나머지 스물한 항목은 안 선다
    - 프로젝트: 대표가 매긴 평가·리셋 감점만 서고, 완료하면 저절로 붙는 +10/+5 는 안 선다
    """
    assert set(_SPLIT_CATEGORIES) == {ScoreCategory.ENV, ScoreCategory.PROJECT}


def test_조건식이_두_예외를_다_담는다():
    """[_contrib_board] 는 목록과 되돌리기가 **같이** 쓰는 조건이다.

    SQL 로 굽혀서 예외 둘이 실제로 들어갔는지 본다 — 파이썬으로 따로 한 번 더
    적으면 언젠가 목록과 되돌리기가 갈린다.
    """
    sql = str(_contrib_board().compile(compile_kwargs={"literal_binds": True}))
    assert CLAIM_ITEM_NAME in sql          # 컴플레인 해결만 집어내는 자리
    assert "created_by_id IS NOT NULL" in sql  # 사람이 매긴 프로젝트 점수만


def test_클레임_이름은_한_곳에서_온다():
    """점수를 붙이는 쪽·승인으로 돌리는 쪽·내역에 세우는 쪽이 같은 이름을 봐야 한다"""
    from app.api.scoring.env import _APPROVAL_ITEMS

    assert _APPROVAL_ITEMS == {CLAIM_ITEM_NAME}
