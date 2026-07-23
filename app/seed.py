"""초기 부트스트랩 시드 — 기본 지점 + 첫 관리자 생성 (멱등).

실행:  docker compose exec api python -m app.seed
값은 .env 의 SEED_* 로 조정.
"""

import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.enums import Rank, Role
from app.models.org.branch import Branch
from app.models.org.employee import Employee
from app.services.barcode import unique_barcode, unique_emp_no


async def seed() -> None:
    async with SessionLocal() as db:
        branch = (
            await db.execute(select(Branch).where(Branch.name == settings.seed_branch_name))
        ).scalar_one_or_none()
        if branch is None:
            branch = Branch(name=settings.seed_branch_name, type="HQ")
            db.add(branch)
            await db.flush()
            print(f"[seed] 지점 생성: {branch.name} ({branch.id})")
        else:
            print(f"[seed] 지점 존재: {branch.name} ({branch.id})")

        admin = (
            await db.execute(select(Employee).where(Employee.email == settings.seed_admin_email))
        ).scalar_one_or_none()
        if admin is None:
            admin = Employee(
                name=settings.seed_admin_name,
                email=settings.seed_admin_email,
                password_hash=hash_password(settings.seed_admin_password),
                branch_id=branch.id,
                rank=Rank.STORE_MANAGER,
                role=Role.ADMIN,
                barcode=await unique_barcode(db),
                emp_no=await unique_emp_no(db),
            )
            db.add(admin)
            print(f"[seed] 관리자 생성: {admin.email}")
        else:
            print(f"[seed] 관리자 존재: {admin.email}")

        await db.commit()
        print("[seed] 완료")


if __name__ == "__main__":
    asyncio.run(seed())
