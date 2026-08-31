"""사내톡 첨부에 박힌 서명을 걷어낸다

앱은 올릴 때 받은 **서명된** 주소(`/files/..?exp&sig`)를 그대로 돌려보내는데
그걸 그냥 담고 있었다. 서명은 7일이면 만료되므로 **일주일 뒤부터 그 사진이
영영 안 뜬다** — 실제로 8월 초에 보낸 사진 세 장이 파일 이름 줄로 떨어져
있었다. `unsign_upload_url` 주석이 경고하던 바로 그 자리다 (§H2).

앞으로 담기는 것은 `post_message` 가 벗겨서 넣고, 내려줄 때
`MessageOut.attachments`(SignedUrl)가 새로 서명한다. 여기서는 **이미 박혀
있는 줄**을 `/uploads/..` 로 되돌린다.

되돌리기는 없다 — 서명을 다시 박는 것은 고장을 되살리는 일이고,
만료 시각도 복원할 수 없다.

Revision ID: atc000000001
Revises: clm000000001
Create Date: 2026-08-31
"""

from alembic import op

revision = "atc000000001"
down_revision = "clm000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 원소마다 '/files/<rel>?exp=..&sig=..' → '/uploads/<rel>'.
    # 이미 '/uploads/..' 인 것과 http 주소는 정규식에 안 걸려 그대로 남는다.
    op.execute(
        """
        UPDATE chat_messages
           SET attachments = (
               SELECT jsonb_agg(
                          regexp_replace(
                              split_part(item #>> '{}', '?', 1),
                              '^/files/', '/uploads/'
                          )
                          ORDER BY ord
                      )
                 FROM jsonb_array_elements(attachments) WITH ORDINALITY AS t(item, ord)
           )
         WHERE jsonb_typeof(attachments) = 'array'
           AND attachments::text LIKE '%/files/%'
        """
    )


def downgrade() -> None:
    pass
