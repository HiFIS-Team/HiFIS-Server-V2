"""운동일지 더미 데이터 — 개발용 (`python -m app.seed_workouts`).

빈 화면으로는 표가 좁은지, 묶음 피드백이 읽히는지, 회원 웹이 제대로 뜨는지
알 수 없어서 **실제로 트레이너가 적는 모양 그대로** 채워 둔다.

두 번 돌려도 안 쌓인다 — 이미 일지가 있는 회원은 건너뛴다.
"""

import asyncio
from datetime import date, timedelta

from sqlalchemy import select

from app.core.tokens import TRAINING_TOKEN_LENGTH, public_token
from app.db.session import SessionLocal
from app.enums import WorkoutKind
from app.models.members.member import Member
from app.models.members.workout import WorkoutLog

#: PT 회차 — (수업내용, 웨이트 줄, 유산소 줄)
_PT = [
    (
        "가슴, 삼두",
        [
            ("가슴", "벤치프레스", "40kg 12회", "4"),
            ("가슴", "인클라인 덤벨프레스", "12kg 12회", "3"),
            ("가슴", "체스트 플라이", "25kg 15회", "3"),
            ("삼두", "케이블 푸시다운", "20kg 15회", "3"),
        ],
        [("트레드밀", "20분")],
    ),
    (
        "등, 이두",
        [
            ("등", "랫풀다운", "40kg 12회", "4"),
            ("등", "시티드 로우", "35kg 12회", "4"),
            ("등", "덤벨 로우", "16kg 12회", "3"),
            ("이두", "덤벨 컬", "8kg 15회", "3"),
        ],
        [("사이클", "15분")],
    ),
    (
        "하체",
        [
            ("하체", "스쿼트", "50kg 10회", "5"),
            ("하체", "레그 프레스", "90kg 12회", "4"),
            ("하체", "레그 익스텐션", "30kg 15회", "3"),
            ("하체", "런지", "맨몸 20보", "3"),
        ],
        [("스텝밀", "10분")],
    ),
    (
        "어깨, 복근",
        [
            ("어깨", "숄더프레스", "20kg 12회", "4"),
            ("어깨", "사이드 레터럴 레이즈", "6kg 15회", "4"),
            ("복근", "행잉 레그레이즈", "맨몸 15회", "3"),
        ],
        [("로잉머신", "12분")],
    ),
    (
        "전신 순환",
        [
            ("전신", "데드리프트", "60kg 8회", "4"),
            ("전신", "케틀벨 스윙", "16kg 20회", "3"),
            ("가슴", "푸시업", "맨몸 20회", "3"),
        ],
        [("트레드밀", "25분")],
    ),
]

#: 개인 운동 — (수업내용, 웨이트, 유산소, 트레이너 총평, 회원이 직접 썼나)
_PERSONAL = [
    (
        "유산소 위주",
        [],
        [("트레드밀", "40분"), ("사이클", "20분")],
        "유산소만 길게 하면 근손실이 와요. 하체 한 종목이라도 같이 해 주세요.",
        True,
    ),
    (
        "가슴 보강",
        [
            ("가슴", "덤벨프레스", "14kg 12회", "4"),
            ("가슴", "푸시업", "맨몸 15회", "4"),
        ],
        [("트레드밀", "15분")],
        "푸시업 내려갈 때 팔꿈치가 벌어지지 않게 45도만 유지해 보세요.",
        True,
    ),
    (
        "하체 보강",
        [
            ("하체", "스쿼트", "맨몸 20회", "4"),
            ("하체", "런지", "맨몸 20보", "3"),
        ],
        [],
        None,
        False,
    ),
]


def _weights(rows: list[tuple[str, str, str, str]]) -> list[dict]:
    return [{"part": p, "name": n, "load": l, "sets": s} for p, n, l, s in rows]


def _cardio(rows: list[tuple[str, str]]) -> list[dict]:
    return [{"name": n, "duration": d} for n, d in rows]


async def seed_workouts() -> None:
    async with SessionLocal() as db:
        members = list((await db.execute(select(Member))).scalars().all())
        if not members:
            print("회원이 없다 — 먼저 회원을 만든다")
            return

        made = 0
        for member in members:
            # 주소가 없는 옛 회원에게도 하나 준다 (마이그레이션 이후에 만들어진 회원 대비)
            if not member.training_token:
                member.training_token = public_token(TRAINING_TOKEN_LENGTH)

            already = await db.scalar(
                select(WorkoutLog.id).where(WorkoutLog.member_id == member.id).limit(1)
            )
            if already:
                continue

            today = date.today()
            for i, (title, weights, cardio) in enumerate(_PT):
                db.add(
                    WorkoutLog(
                        member_id=member.id,
                        kind=WorkoutKind.PT,
                        session_no=i + 1,
                        title=title,
                        # 주 2회로 거슬러 올라간다 — 1회차가 가장 오래됐다
                        performed_on=today - timedelta(days=(len(_PT) - i) * 3),
                        author_id=member.owner_trainer_id,
                        weights=_weights(weights),
                        cardio=_cardio(cardio),
                        media=[],
                        trainer_feedback=None,
                    )
                )
                made += 1

            for i, (title, weights, cardio, feedback, by_member) in enumerate(_PERSONAL):
                db.add(
                    WorkoutLog(
                        member_id=member.id,
                        kind=WorkoutKind.PERSONAL,
                        session_no=None,
                        title=title,
                        performed_on=today - timedelta(days=i * 4 + 1),
                        # 비어 있으면 회원이 웹에서 직접 쓴 줄이다
                        author_id=None if by_member else member.owner_trainer_id,
                        weights=_weights(weights),
                        cardio=_cardio(cardio),
                        media=[],
                        trainer_feedback=feedback,
                    )
                )
                made += 1

        await db.commit()
        print(f"운동일지 {made}장 · 회원 {len(members)}명")
        for member in members:
            print(f"  {member.name} → /training/{member.training_token}")


if __name__ == "__main__":
    asyncio.run(seed_workouts())
