import asyncio
import os
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Literal, Protocol, cast

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings

type AsyncCheck = Callable[[], Awaitable[None]]


class ComponentCheck(BaseModel):
    status: Literal["ok", "error"]
    error_code: str | None = None


class ReadinessReport(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, ComponentCheck]


class ReadinessProbe(Protocol):
    async def check(self) -> ReadinessReport:
        """Check all required dependencies without leaking sensitive details."""


class ReadinessCheckError(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


async def check_artifact_directory(artifact_root: Path) -> None:
    await asyncio.to_thread(_probe_artifact_directory, artifact_root)


def _probe_artifact_directory(artifact_root: Path) -> None:
    if not artifact_root.is_dir():
        raise ReadinessCheckError("artifacts_unavailable")

    probe_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=artifact_root,
            prefix=".readiness-",
            delete=False,
        ) as probe_file:
            probe_path = Path(probe_file.name)
            probe_file.write(b"ready")
            probe_file.flush()
            os.fsync(probe_file.fileno())
    finally:
        if probe_path is not None:
            probe_path.unlink(missing_ok=True)


async def check_postgresql(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def check_redis(redis_client: Redis) -> None:
    ping_succeeded = await cast(Awaitable[bool], redis_client.ping())
    if not ping_succeeded:
        raise ReadinessCheckError("redis_unavailable")


async def check_migrations(engine: AsyncEngine, alembic_config_path: Path) -> None:
    expected_heads = await asyncio.to_thread(_get_expected_migration_heads, alembic_config_path)
    async with engine.connect() as connection:
        current_heads = await connection.run_sync(_get_current_migration_heads)
    if set(current_heads) != set(expected_heads):
        raise ReadinessCheckError("migrations_not_current")


def _get_expected_migration_heads(alembic_config_path: Path) -> tuple[str, ...]:
    config = AlembicConfig(str(alembic_config_path))
    return tuple(ScriptDirectory.from_config(config).get_heads())


def _get_current_migration_heads(connection: Connection) -> tuple[str, ...]:
    return tuple(MigrationContext.configure(connection).get_current_heads())


def build_infrastructure_readiness_probe(
    *,
    settings: Settings,
    engine: AsyncEngine,
    redis_client: Redis,
) -> "CompositeReadinessProbe":
    async def postgresql_check() -> None:
        await check_postgresql(engine)

    async def redis_check() -> None:
        await check_redis(redis_client)

    async def artifact_check() -> None:
        await check_artifact_directory(settings.artifact_root)

    async def migration_check() -> None:
        await check_migrations(engine, settings.alembic_config_path)

    return CompositeReadinessProbe(
        checks={
            "postgresql": postgresql_check,
            "redis": redis_check,
            "artifacts": artifact_check,
            "migrations": migration_check,
        },
        timeout_seconds=settings.readiness_timeout_seconds,
    )


class CompositeReadinessProbe:
    def __init__(self, *, checks: Mapping[str, AsyncCheck], timeout_seconds: float) -> None:
        self._checks = dict(checks)
        self._timeout_seconds = timeout_seconds

    async def check(self) -> ReadinessReport:
        component_results = await asyncio.gather(
            *(
                self._check_component(component_name, check)
                for component_name, check in self._checks.items()
            )
        )
        checks = dict(component_results)
        status: Literal["ready", "not_ready"] = (
            "ready" if all(check.status == "ok" for check in checks.values()) else "not_ready"
        )
        return ReadinessReport(status=status, checks=checks)

    async def _check_component(
        self,
        component_name: str,
        check: AsyncCheck,
    ) -> tuple[str, ComponentCheck]:
        try:
            await asyncio.wait_for(check(), timeout=self._timeout_seconds)
        except TimeoutError:
            return component_name, ComponentCheck(
                status="error",
                error_code=f"{component_name}_timeout",
            )
        except ReadinessCheckError as exc:
            return component_name, ComponentCheck(status="error", error_code=exc.error_code)
        except Exception:
            return component_name, ComponentCheck(
                status="error",
                error_code=f"{component_name}_unavailable",
            )
        return component_name, ComponentCheck(status="ok")


class NotConfiguredReadinessProbe:
    async def check(self) -> ReadinessReport:
        return ReadinessReport(
            status="not_ready",
            checks={
                "configuration": ComponentCheck(
                    status="error",
                    error_code="readiness_not_configured",
                )
            },
        )
