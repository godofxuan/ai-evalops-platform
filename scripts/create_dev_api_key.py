import argparse
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.auth.api_keys import GeneratedAPIKey, generate_api_key
from app.core.config import Settings
from app.core.event_loop import run_with_psycopg_compatible_event_loop
from app.domain.enums import TenantStatus
from app.persistence.database import create_database_engine, create_session_factory
from app.persistence.orm_models import APIKey, Tenant

_SAFE_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def parse_tenant_slug(value: str) -> str:
    if _SAFE_SLUG.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "tenant slug must be 1-63 lowercase letters, digits, or internal hyphens"
        )
    return value


def positive_days(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expires-in-days must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a tenant and one API key whose plaintext is shown once."
    )
    parser.add_argument("--tenant-slug", required=True, type=parse_tenant_slug)
    parser.add_argument("--tenant-name")
    parser.add_argument("--key-name", default="development")
    parser.add_argument("--expires-in-days", type=positive_days)
    parser.add_argument(
        "--human-reviewer",
        action="store_true",
        help="Mark this credential as eligible for human review endpoints.",
    )
    parser.add_argument(
        "--review-task-creator",
        action="store_true",
        help="Allow this credential to create or expand human review tasks.",
    )
    return parser


def format_created_key_message(
    generated: GeneratedAPIKey,
    *,
    tenant_id: UUID,
    tenant_slug: str,
) -> str:
    plaintext = generated.plaintext.get_secret_value()
    return "\n".join(
        (
            f"Tenant: {tenant_slug} ({tenant_id})",
            f"API key prefix: {generated.prefix}",
            f"API key (shown once): {plaintext}",
            "Store the API key now; the database contains only its scrypt hash.",
        )
    )


async def create_key(
    *,
    settings: Settings,
    tenant_slug: str,
    tenant_name: str,
    key_name: str,
    expires_in_days: int | None,
    can_review: bool = False,
    can_create_review_tasks: bool = False,
) -> tuple[GeneratedAPIKey, UUID]:
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory.begin() as session:
            tenant = (
                await session.execute(select(Tenant).where(Tenant.slug == tenant_slug))
            ).scalar_one_or_none()
            if tenant is None:
                tenant = Tenant(slug=tenant_slug, name=tenant_name)
                session.add(tenant)
                await session.flush()
            elif tenant.status is not TenantStatus.ACTIVE:
                raise RuntimeError("cannot create an API key for a disabled tenant")

            generated = generate_api_key()
            expires_at = (
                datetime.now(UTC) + timedelta(days=expires_in_days)
                if expires_in_days is not None
                else None
            )
            session.add(
                APIKey(
                    tenant_id=tenant.id,
                    name=key_name,
                    key_prefix=generated.prefix,
                    key_hash=generated.key_hash,
                    expires_at=expires_at,
                    can_review=can_review,
                    can_create_review_tasks=can_create_review_tasks,
                )
            )
            await session.flush()
            tenant_id = tenant.id
    finally:
        await engine.dispose()
    return generated, tenant_id


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    generated, tenant_id = run_with_psycopg_compatible_event_loop(
        create_key(
            settings=Settings(),
            tenant_slug=arguments.tenant_slug,
            tenant_name=arguments.tenant_name or arguments.tenant_slug,
            key_name=arguments.key_name,
            expires_in_days=arguments.expires_in_days,
            can_review=arguments.human_reviewer,
            can_create_review_tasks=arguments.review_task_creator,
        )
    )
    print(
        format_created_key_message(
            generated,
            tenant_id=tenant_id,
            tenant_slug=arguments.tenant_slug,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
