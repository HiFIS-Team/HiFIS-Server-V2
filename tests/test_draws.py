"""매장 TV 추첨 — 규칙을 못 박아 둔다 (2026-09-01 대표 결정).

    | | |
    |---|---|
    | 대상 | **전달**에 친절도 설문을 낸 회원 (8월 설문 → 9월 추첨) |
    | 뽑는 날 | 매월 1일, 잡이 자동으로 |
    | 이름 | 가운데를 가린다 (`김은후` → `김○후`) |
    | 첫 게임 | 구슬 레이스 |

깨지면 고치기 전에 의도한 변경인지 먼저 확인한다. 이 값들이 매장 벽에
걸리는 화면을 정한다.
"""

from datetime import datetime

import pytest

from app.core.periods import KST
from app.enums import DrawGame
from app.services.draws import (
    WINNERS,
    DRAW_DAY,
    GAME_ROTATION,
    draw_period,
    game_of,
    mask_name,
    mask_phone,
    pick,
    source_period,
)


class Test대상달:
    """"8월에 설문 낸 사람이 9월 이벤트 참여" — 이 한 줄이 규칙 전부다."""

    def test_바로_전달을_본다(self):
        assert source_period("2026-09") == "2026-08"

    def test_해를_넘어가도_맞다(self):
        assert source_period("2026-01") == "2025-12"

    def test_십이월(self):
        assert source_period("2026-12") == "2026-11"


class Test이름가리기:
    """회원들이 보는 화면이라 이름을 그대로 안 건다."""

    @pytest.mark.parametrize(
        ("name", "want"),
        [
            ("김은후", "김○후"),   # 셋 — 가운데
            ("김민", "김○"),       # 둘 — 뒤
            ("남궁민수", "남○○수"),  # 넷 — 가운데 전부
            ("박", "박"),           # 하나 — 가릴 데가 없다
            ("  이재현  ", "이○현"),  # 앞뒤 공백은 떼고 센다
            ("", ""),
        ],
    )
    def test_가운데를_가린다(self, name, want):
        assert mask_name(name) == want

    def test_전화는_뒤_네_자리만(self):
        assert mask_phone("010-1234-5678") == "···5678"
        assert mask_phone("010") == "···"


class Test게임차례:
    def test_첫_달은_구슬_레이스다(self):
        # 2026-09 가 첫 이벤트다 (2026-09-01 대표 결정)
        assert game_of("2026-09") is DrawGame.RACE

    def test_달마다_바뀐다(self):
        assert game_of("2026-10") is not game_of("2026-09")

    def test_한_바퀴_돌면_되돌아온다(self):
        n = len(GAME_ROTATION)
        assert game_of("2026-09") is game_of(f"2026-{9 + n:02d}")

    def test_해를_넘겨도_차례가_안_끊긴다(self):
        assert game_of("2027-01") is GAME_ROTATION[4 % len(GAME_ROTATION)]

    def test_화면이_있는_게임만_돈다(self):
        """안 만든 게임을 넣어 두면 그 달에 TV 가 빈 화면이 된다."""
        assert DrawGame.LADDER not in GAME_ROTATION
        assert DrawGame.ROULETTE not in GAME_ROTATION


class Test추첨달판정:
    """[DRAW_DAY] 전에는 아직 지난달 것이 TV 에 걸려 있다."""

    def test_뽑는_날_당일부터_그_달이다(self):
        assert draw_period(datetime(2026, 9, DRAW_DAY, 9, tzinfo=KST)) == "2026-09"

    def test_말일까지_그대로다(self):
        assert draw_period(datetime(2026, 9, 30, 23, 59, tzinfo=KST)) == "2026-09"

    def test_다음_달_첫날이면_넘어간다(self):
        assert draw_period(datetime(2026, 10, 1, 0, 1, tzinfo=KST)) == "2026-10"

    @pytest.mark.skipif(DRAW_DAY == 1, reason="1일에 뽑으면 '뽑기 전'이 없다")
    def test_뽑기_전에는_지난달이다(self):
        before = datetime(2026, 9, DRAW_DAY - 1, 12, tzinfo=KST)
        assert draw_period(before) == "2026-08"

    def test_해를_넘길_때(self):
        assert draw_period(datetime(2027, 1, 1, 0, 0, tzinfo=KST)) == "2027-01"


class Test당첨자뽑기:
    def test_참가자가_없으면_안_뽑는다(self):
        assert pick([]) == []

    def test_한_명이면_그_사람만(self):
        """셋을 뽑으랬다고 없는 사람을 만들지 않는다."""
        assert pick([{"name": "김은후"}]) == [0]

    def test_세_명을_뽑는다(self):
        people = [{"name": str(i)} for i in range(7)]
        for _ in range(200):
            got = pick(people)
            assert len(got) == WINNERS
            assert all(0 <= i < 7 for i in got)

    def test_같은_사람을_두_번_안_뽑는다(self):
        """세 자리에 같은 사람이 들어가면 그 사람이 1등이자 2등이 된다."""
        people = [{"name": str(i)} for i in range(4)]
        for _ in range(300):
            got = pick(people)
            assert len(set(got)) == len(got)

    def test_한_사람에게_몰리지_않는다(self):
        """`secrets` 로 뽑는다 — 200번에 늘 같은 사람이면 뽑는 게 아니다."""
        people = [{"name": str(i)} for i in range(5)]
        got = {i for _ in range(200) for i in pick(people)}
        assert len(got) == 5

    def test_1등_자리도_고루_돈다(self):
        """차례가 곧 1·2·3등이라 첫 칸이 굳으면 안 된다."""
        people = [{"name": str(i)} for i in range(5)]
        first = {pick(people)[0] for _ in range(200)}
        assert len(first) == 5
