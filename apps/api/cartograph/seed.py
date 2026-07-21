"""Seed a demo tenant + dispatcher user for local development.

Usage:
    uv run python -m cartograph.seed [email] [password]

Defaults: dispatcher@example.com / cartograph-dev
Idempotent — re-running updates the existing user's password.
"""

from __future__ import annotations

import asyncio
import sys

import structlog
from sqlalchemy import select

from cartograph.auth.models import Tenant, User
from cartograph.auth.security import hash_password
from cartograph.database import AsyncSessionLocal

log = structlog.get_logger()

DEMO_SLUG = "demo"


async def seed(email: str, password: str) -> None:
    async with AsyncSessionLocal() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == DEMO_SLUG))
        ).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(slug=DEMO_SLUG, name="Demo Courier Co")
            session.add(tenant)
            await session.flush()
            log.info("tenant created", slug=DEMO_SLUG, tenant_id=str(tenant.id))

        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            user = User(tenant_id=tenant.id, email=email, password_hash=hash_password(password))
            session.add(user)
            log.info("user created", email=email)
        else:
            user.password_hash = hash_password(password)
            log.info("user password updated", email=email)

        await session.commit()


def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else "dispatcher@example.com"
    password = sys.argv[2] if len(sys.argv) > 2 else "cartograph-dev"
    asyncio.run(seed(email.lower(), password))


if __name__ == "__main__":
    main()
