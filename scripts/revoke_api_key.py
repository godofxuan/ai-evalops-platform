import argparse
import re
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import update

from app.core.config import Settings
from app.core.event_loop import run_with_psycopg_compatible_event_loop
from app.domain.enums import APIKeyStatus
from app.persistence.database import create_database_engine, create_session_factory
from app.persistence.orm_models import APIKey

_SAFE_PREFIX = re.compile(r"^evk_[0-9a-f]{12}$")


def parse_safe_prefix(value: str) -> str:
    if _SAFE_PREFIX.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "expected only a safe API key prefix such as evk_001122334455"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Revoke an active API key by its non-secret audit prefix."
    )
    parser.add_argument("prefix", type=parse_safe_prefix)
    return parser


async def revoke_key(*, settings: Settings, prefix: str) -> bool:
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory.begin() as session:
            revoked_id = (
                await session.execute(
                    update(APIKey)
                    .where(
                        APIKey.key_prefix == prefix,
                        APIKey.status == APIKeyStatus.ACTIVE,
                    )
                    .values(
                        status=APIKeyStatus.REVOKED,
                        revoked_at=datetime.now(UTC),
                    )
                    .returning(APIKey.id)
                )
            ).scalar_one_or_none()
    finally:
        await engine.dispose()
    return revoked_id is not None


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    revoked = run_with_psycopg_compatible_event_loop(
        revoke_key(settings=Settings(), prefix=arguments.prefix)
    )
    if not revoked:
        print(f"No active API key found for prefix {arguments.prefix}.")
        return 1
    print(f"Revoked API key prefix {arguments.prefix}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
