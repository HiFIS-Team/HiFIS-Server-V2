"""PT 만족도 폼의 객관식 항목표 (2026-09-16).

## 왜 테스트가 있나 — **만들면서 실제로 당했다**

모델에 `improve` 칸을 선언하는 줄을 빠뜨린 채로 라우터가
`survey.improve = [...]` 를 했다. SQLAlchemy 모델은 **선언 안 된 이름에
값을 넣어도 조용히 받는다** — 파이썬 객체의 속성으로만 붙고 커밋 때 버려진다.

그래서 **201 이 나오고 화면은 '잘 받았어요' 로 끝나는데 답이 안 남았다.**
로그인이 없는 자리라 회원에게 다시 써 달라고 할 수도 없다.

아래 `test_모델에_두_칸이_실제로_있다` 가 그 자리를 막는다.
"""

from sqlalchemy import inspect

from app.models.members.pt_survey import PtSurvey
from app.schemas.members.pt_survey import PtSurveySubmit
from app.services import pt_topics


def test_모델에_두_칸이_실제로_있다():
    """**선언이 빠져도 대입은 성공한다** — 그래서 컬럼으로 있는지를 본다."""
    columns = {c.key for c in inspect(PtSurvey).mapper.column_attrs}
    assert {"praise", "improve"} <= columns


def test_주제_코드가_안_겹친다():
    codes = [t.code for t in (*pt_topics.PT_TOPICS, *pt_topics.RETIRED)]
    assert len(codes) == len(set(codes))


def test_주제마다_두_문구가_다_있다():
    for t in pt_topics.PT_TOPICS:
        assert t.praise.strip() and t.improve.strip()
        # 같은 말이면 화면 둘이 똑같아 보인다 — 칭찬형·요청형으로 갈려야 한다
        assert t.praise != t.improve


def test_모르는_코드는_코드를_그대로_돌려준다():
    """빈칸으로 두면 표에서 실수로 지운 것을 아무도 못 알아챈다."""
    assert pt_topics.label_of("NOPE", praise=True) == "NOPE"
    assert pt_topics.label_of("DIET", praise=True) != pt_topics.label_of("DIET", praise=False)


def _submit(**kw):
    return PtSurveySubmit(satisfaction=5, renew="YES", **kw)


def test_모르는_주제와_겹치는_주제를_버린다():
    """**422 를 내지 않는다** — 회원의 답 전체를 물리는 것보다 낫다."""
    got = _submit(
        improve=[
            {"topic": "EXPLAIN", "note": "처음 동작만 더 설명해주세요"},
            {"topic": "NOPE", "note": "표에 없는 주제"},
            {"topic": "EXPLAIN", "note": "같은 주제 두 번째"},
        ]
    )
    assert [a.topic for a in got.improve] == ["EXPLAIN"]
    # 먼저 고른 쪽의 글이 남는다
    assert got.improve[0].note == "처음 동작만 더 설명해주세요"


def test_공백만_적은_글은_비운다():
    """빈 문자열로 남기면 '글을 적었다' 로 세어진다."""
    got = _submit(praise=[{"topic": "DIET", "note": "   "}])
    assert got.praise[0].note is None


def test_글이_너무_길면_자른다():
    got = _submit(praise=[{"topic": "DIET", "note": "가" * 900}])
    assert len(got.praise[0].note) == pt_topics.MAX_NOTE
