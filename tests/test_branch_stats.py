from app.api.scoring.branch_stats import clean_name


def test_clean_name_merges_old_labels():
    assert clean_name("기존38") == "기존"
    assert clean_name("일권10명") == "일권"
    assert clean_name(" 신규 ") == "신규"
    assert clean_name("123") == "123"
