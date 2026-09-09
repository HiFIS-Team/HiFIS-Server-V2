"""동광주 지점을 걷어낸다 (2026-09-09 대표 결정)

동광주가 화순·첨단과 **운영이 갈라져** 이 앱에서 쓸 일이 없어졌다.
`share_group` 으로 서로 안 보이게만 해 두었던 것(`bgrp00000001`)을
지점째 빼는 것으로 바꾼다.

**적용된 마이그레이션을 고치지 않고 새로 하나 얹는다.**
`c1d2e3f4a5b6`(동광주첨단 → 첨단·동광주 분리)가 **빈 DB 에서도 무조건**
동광주를 만들기 때문에, 그 파일을 손대는 대신 여기서 지운다 —
새로 만드는 DB 도 만들었다가 곧바로 지우므로 결과가 같다.
`8b9c0d1e2f3a`(급여 주기)가 심는 동광주 정책 두 줄도 여기서 같이 걷힌다.

**사람이 남아 있으면 중단한다.** 지점을 지우면 그 사람의 소속이 갈 곳을
잃고, 근태·급여·점수가 지점 없이 떠돈다. 옮기거나 퇴사 처리를 먼저 한다.
회원도 같다 — 등록권·세션 싸인·운동일지가 딸려 있다.

운영 확인 (2026-09-09): 직원 0 · 회원 0 · 프로젝트 0 · 회의록 0 ·
환경정비 기록 0 · 추첨 0. 남아 있던 것은 `env_items` 22(자동 시드) ·
`invite_keys` 5(3장 만료·2장 사용됨, 그 사람들은 이미 딴 데로 갔다) ·
`payday_policies` 2 뿐이다.

**되돌리지 않는다** — 지점 id 가 새로 생겨서 옛 공개 주소(설문·TV·기록)와
QR 종이가 어차피 못 살아난다. 지운 행은 배포 전에 따로 받아 두었다.
"""

import sqlalchemy as sa
from alembic import op

revision = "dgj000000001"
down_revision = "sms000000001"
branch_labels = None
depends_on = None

_NAME = "동광주"

#: 딸린 것부터 지운다 — 뒤 테이블을 앞에서 참조하므로 순서가 곧 제약이다
#: (`env_task_logs` 가 `env_items` 를, 나머지는 `branches` 를 본다)
_TABLES = (
    "env_task_logs",
    "supply_orders",
    "my_task_misses",
    "score_events",
    "draws",
    "meetings",
    "projects",
    "invite_keys",
    "payday_policies",
    "rank_policies",
    "hourly_wage_policies",
    "env_items",
)


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT id FROM branches WHERE name = :n"), {"n": _NAME}
    ).fetchone()
    if row is None:
        return  # 이미 없다 — 새로 만든 DB 에서 이 순서가 앞설 때도 안전하다
    branch_id = row[0]

    # 사람·회원이 남아 있으면 손대지 않는다. 조용히 지우면 그 기록들이
    # 지점 없이 떠돌고, 무엇이 사라졌는지 나중에 되짚을 수가 없다.
    for table, what in (("employees", "직원"), ("members", "회원")):
        left = conn.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE branch_id = :b"),
            {"b": branch_id},
        ).scalar()
        if left:
            raise RuntimeError(
                f"{_NAME}에 {what} {left}명이 남아 있어 지점 삭제를 중단합니다. "
                f"다른 지점으로 옮기거나 정리한 뒤 다시 실행하세요."
            )

    for table in _TABLES:
        # 테이블이 아직 없을 수 있다 — 이 마이그레이션보다 뒤에 생기는 것은
        # 없지만, 되돌렸다 다시 올리는 동안 순서가 어긋나도 안 죽게 둔다
        exists = conn.execute(
            sa.text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
        ).scalar()
        if exists is None:
            continue
        conn.execute(
            sa.text(f"DELETE FROM {table} WHERE branch_id = :b"), {"b": branch_id}
        )

    conn.execute(sa.text("DELETE FROM branches WHERE id = :b"), {"b": branch_id})


def downgrade() -> None:
    # 되살리지 않는다 — 새 id 로 만들어 봐야 옛 공개 주소·QR 이 안 맞는다
    pass
