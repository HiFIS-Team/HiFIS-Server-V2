"""할 일에서 나온 환경정비 점수는 **할 일이 사라질 때 같이 걷힌다** (2026-09-21).

프로젝트 할 일 이름이 환경정비 항목과 맞으면 체크하는 순간 수행 기록과
점수가 붙는다 (`_award_todo_env`). 걷는 쪽(`retract_todo_env`)은 **체크를
풀 때만** 불렸고, 할 일이 사라지는 나머지 길 셋은 안 불렀다.

| 길 | 나던 일 |
|---|---|
| `delete_project_todo` | 체크 → 점수 → 할 일만 삭제. 점수가 남는다 |
| `_purge_project` | 프로젝트째 지워도 환경정비 점수만 남는다 |
| `reset_project` | 체크만 풀려서, 다시 체크하면 **점수가 두 배** |

첫째 길은 되풀이할 수 있어서 점수를 무한히 쌓는 길이었다 —
`현수막`(10점)·`클레임해결`(15점)처럼 사진·대표 승인이 걸린 항목까지
그 검사를 안 거치고 붙었다 (`_award_todo_env` 는 `POST /env-logs` 가 아니다).

## 왜 원본을 읽나

DB 를 띄우지 않는 테스트라 실제로 점수가 걷히는지는 못 본다. 대신 **걷는
함수를 부르기는 하는지**를 본다 — 이 사고는 "부르는 걸 빠뜨렸다" 하나였고,
네 번째 길이 생길 때 같은 식으로 또 빠지는 것을 여기서 잡는다.
"""

import ast
import inspect

from app.api.projects import projects

#: 체크된 할 일이 **체크된 상태를 잃는** 자리 — 전부 점수를 걷어야 한다
MUST_RETRACT = (
    "update_project_todo",   # 체크 해제
    "delete_project_todo",   # 할 일 삭제
    "_purge_project",        # 프로젝트 삭제 (직접 · 삭제 결재 승인)
    "reset_project",         # 완료 리셋 — 전부 체크 해제
)

RETRACTOR = "retract_todo_env"


def _calls(func_name: str) -> set[str]:
    """그 함수 몸통에서 부르는 이름들 — 중첩 호출까지 이름만 모은다."""
    tree = ast.parse(inspect.getsource(getattr(projects, func_name)))
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_할일이_사라지는_길은_전부_점수를_걷는다():
    missing = [name for name in MUST_RETRACT if RETRACTOR not in _calls(name)]
    assert not missing, f"{missing} 가 {RETRACTOR} 를 안 부른다 — 점수가 남는다"


def test_걷는_함수가_붙이는_함수와_짝이다():
    """붙이는 쪽이 사라지면 이 테스트도 뜻을 잃는다 — 같이 있는지 본다."""
    assert hasattr(projects, "_award_todo_env")
    assert hasattr(projects, RETRACTOR)


def test_할일_자동적립은_확인이_걸린_항목을_뺀다():
    """`POST /env-logs` 의 사진·메모·승인 검사를 이 길도 거쳐야 한다.

    할 일에는 사진을 실을 자리도 결재를 걸 자리도 없다. 검사를 안 하면
    `클레임해결`(15점)이 대표 승인 없이, `현수막`(10점)이 사진 없이 붙는다.
    """
    assert "auto_awardable" in _calls("_award_todo_env")


def test_auto_awardable_이_세_검사를_그대로_쓴다():
    """이름을 베껴 두면 `PHOTO_REQUIRED_ITEMS` 가 늘 때 이쪽만 안 따라온다."""
    from app.api.scoring import env

    body = inspect.getsource(env.auto_awardable)
    for guard in ("_needs_photo", "_needs_note", "_needs_approval"):
        assert guard in body, f"{guard} 를 안 본다"
