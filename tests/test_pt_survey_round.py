from app.api.members.session_signs import is_pt_survey_round


def test_first_at_7_then_every_10():
    rounds = [n for n in range(1, 60) if is_pt_survey_round(n)]
    assert rounds == [7, 17, 27, 37, 47, 57]
