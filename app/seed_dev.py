"""개발/테스트 시드 — 권한별 테스트 계정 + 직급 급여정책 (멱등).

app.seed(부트스트랩: 지점 + MASTER)에 더해, 앱 연동 테스트에 필요한
MEMBER(트레이너)·MANAGER(점장) 계정과 그 직급의 RankPolicy 를 만든다.
비밀번호는 매 실행마다 아래 값으로 재설정 → 항상 알려진 값(개발 전용).

실행:  docker compose exec api python -m app.seed_dev
⚠️ 프로덕션에서 쓰지 말 것(고정 비밀번호).
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.enums import EmployeeStatus, Rank, Role
from app.models.payroll.rank_policy import RankPolicy
from app.models.staff.branch import Branch
from app.models.staff.employee import Employee
from app.services.employee_codes import unique_emp_no

EFFECTIVE_FROM = datetime(2000, 1, 1, tzinfo=timezone.utc)

# (rank, base_salary, new_rate, renewal_rate)
POLICIES = [
    (Rank.TRAINER, 800_000, 0.4, 0.5),
    (Rank.STORE_MANAGER, 2_000_000, 0.4, 0.5),
]

# (email, password, name, rank, role) — 권한 계층 순(MASTER>ADMIN>MANAGER>MEMBER)
# ADMIN 은 어느 직급에도 자동 매핑 안 됨 → 여기서 role 을 명시 지정(rank 는 급여용, 무관).
ACCOUNTS = [
    ("master@hifis.local", "master1234", "테스트 마스터", Rank.CEO, Role.MASTER),
    ("admin2@hifis.local", "admin1234", "테스트 관리자", Rank.STORE_MANAGER, Role.ADMIN),
    ("manager@hifis.local", "manager1234", "테스트 점장", Rank.STORE_MANAGER, Role.MANAGER),
    ("trainer@hifis.local", "trainer1234", "테스트 트레이너", Rank.TRAINER, Role.MEMBER),
]


async def seed_dev() -> None:
    async with SessionLocal() as db:
        branch = (
            await db.execute(select(Branch).where(Branch.name == settings.seed_branch_name))
        ).scalar_one_or_none()
        if branch is None:
            branch = Branch(name=settings.seed_branch_name, type="HQ")
            db.add(branch)
            await db.flush()
            print(f"[seed_dev] 지점 생성: {branch.name} ({branch.id})")

        # ── 직급 급여정책(전사 기본) — 없으면 생성 ──
        for rank, base, new_rate, renewal_rate in POLICIES:
            exists = (
                await db.execute(
                    select(RankPolicy).where(
                        RankPolicy.rank == rank, RankPolicy.branch_id.is_(None)
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                db.add(
                    RankPolicy(
                        rank=rank,
                        base_salary=base,
                        new_rate=new_rate,
                        renewal_rate=renewal_rate,
                        branch_id=None,
                        effective_from=EFFECTIVE_FROM,
                    )
                )
                print(f"[seed_dev] 급여정책 생성: {rank.value} 기본급 {base:,}")
            else:
                print(f"[seed_dev] 급여정책 존재: {rank.value}")

        # ── 테스트 계정 — 비밀번호는 매 실행 재설정(항상 알려진 값) ──
        for email, password, name, rank, role in ACCOUNTS:
            emp = (
                await db.execute(select(Employee).where(Employee.email == email))
            ).scalar_one_or_none()
            if emp is None:
                emp = Employee(
                    name=name,
                    email=email,
                    password_hash=hash_password(password),
                    branch_id=branch.id,
                    rank=rank,
                    role=role,
                    status=EmployeeStatus.ACTIVE,
                    avatar_color="#6366f1",
                    emp_no=await unique_emp_no(db),
                )
                db.add(emp)
                print(f"[seed_dev] 계정 생성: {email} / {password}  ({role.value}·{rank.value})")
            else:
                emp.password_hash = hash_password(password)  # 항상 알려진 값으로
                emp.role = role
                emp.rank = rank
                emp.status = EmployeeStatus.ACTIVE
                emp.deleted_at = None
                emp.token_version += 1  # 기존 세션 무효화(비번 재설정)
                print(f"[seed_dev] 계정 갱신: {email} / {password}  (비번 재설정)")

        await db.commit()
        print("[seed_dev] 완료 — 위 이메일/비밀번호로 로그인")


if __name__ == "__main__":
    asyncio.run(seed_dev())
