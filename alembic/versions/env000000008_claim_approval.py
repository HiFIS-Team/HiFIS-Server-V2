"""환경정비 `클레임해결` 을 대표 승인제로 (2026-09-09 대표 요청)

15점짜리라 칩을 누르기만 하면 가져갈 수 있었다. 컴플레인 해결 완료는 원래
대표 승인을 받는데(`kindness_surveys.improvement_status`), **같은 일을 칩으로
누르면 그냥 들어갔다** — 한 컴플레인에 세 사람이 45점을 가져갈 수 있었다.

실제로 났다 (2026-09-09) — 유찬빈이 칩을 누르고, 전상현이 컴플레인 완료를
올리고, 승인이 나면서 자동 기록이 하나 더 생겼다. 전상현이 중복을 지우려다
자기 것 둘을 다 지워서 **정작 해결한 사람이 0점**이 됐다.

`approval_status` 는 **`클레임해결` 에만 채운다.** 나머지 항목은 `None` 이라
지금처럼 누르는 즉시 점수가 붙는다 — 세탁·청소까지 승인을 받게 하면 대표가
하루에 수십 번을 눌러야 한다.

이미 쌓인 기록은 **전부 `None` 으로 둔다.** 옛 클레임해결도 그냥 둔다 —
이미 점수가 나간 것을 소급해서 대기로 돌리면 랭킹이 흔들린다.
"""

import sqlalchemy as sa
from alembic import op

revision = "env000000008"
down_revision = "env000000007"
branch_labels = None
depends_on = None

_STATUS = sa.Enum(
    "PENDING", "APPROVED", "REJECTED",
    name="projectrequeststatus", native_enum=False, length=20,
)


def upgrade() -> None:
    op.add_column("env_task_logs", sa.Column("approval_status", _STATUS, nullable=True))
    op.add_column("env_task_logs", sa.Column("decided_by_id", sa.String(36), nullable=True))
    op.add_column(
        "env_task_logs", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("env_task_logs", sa.Column("reject_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_env_task_logs_decided_by", "env_task_logs", "employees", ["decided_by_id"], ["id"]
    )
    # 대기 중인 것만 훑는 자리가 결재함이다 — 부분 인덱스로 충분하다
    op.create_index(
        "ix_env_task_logs_pending",
        "env_task_logs",
        ["approval_status"],
        postgresql_where=sa.text("approval_status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("ix_env_task_logs_pending", table_name="env_task_logs")
    op.drop_constraint("fk_env_task_logs_decided_by", "env_task_logs", type_="foreignkey")
    for col in ("reject_reason", "decided_at", "decided_by_id", "approval_status"):
        op.drop_column("env_task_logs", col)
