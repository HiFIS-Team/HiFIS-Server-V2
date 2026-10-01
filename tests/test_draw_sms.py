"""추첨 당첨 문자 — 지점마다 상품이 다르다 (2026-09-30 대표 결정).

깨지면 회원이 받을 상품이 틀리게 나간다 — 고치기 전에 의도한 변경인지 확인한다.
"""

from app.services.draws import winner_text


def test_첨단은_등수마다_상품이_다르다():
    first = winner_text("첨단", "2026-10", 1, "김회원")
    third = winner_text("첨단", "2026-10", 3, "김회원")
    assert "9월 설문 이벤트 1등에" in first and "회원권 3개월" in first
    assert "3등" in third and "회원권 1개월" in third


def test_화순은_다_같아서_등수를_안_적는다():
    text = winner_text("화순", "2026-10", 2, "박회원")
    assert "등에 당첨" not in text
    assert "회원권 1개월" in text and "[피트니스스타 화순점]" in text


def test_상품을_모르는_지점은_안_보낸다():
    assert winner_text("동광주", "2026-10", 1, "이회원") is None
    assert winner_text("화순", "2026-10", 4, "이회원") is None
