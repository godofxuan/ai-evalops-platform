import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.health.service import CompositeReadinessProbe, check_artifact_directory


def _list_directory(path: Path) -> list[Path]:
    return list(path.iterdir())


async def test_composite_readiness_redacts_dependency_exception_details() -> None:
    database_url_with_secret = "postgresql://user:never-return-this@database/evalops"

    async def healthy_check() -> None:
        return None

    async def failing_postgresql_check() -> None:
        raise RuntimeError(database_url_with_secret)

    checks: dict[str, Callable[[], Awaitable[None]]] = {
        "postgresql": failing_postgresql_check,
        "redis": healthy_check,
        "artifacts": healthy_check,
        "migrations": healthy_check,
    }
    probe = CompositeReadinessProbe(checks=checks, timeout_seconds=0.5)

    report = await probe.check()

    assert report.status == "not_ready"
    assert report.checks["postgresql"].status == "error"
    assert report.checks["postgresql"].error_code == "postgresql_unavailable"
    assert database_url_with_secret not in report.model_dump_json()


async def test_artifact_directory_check_verifies_writes_without_leaving_probe_files(
    tmp_path: Path,
) -> None:
    await check_artifact_directory(tmp_path)

    entries = await asyncio.to_thread(_list_directory, tmp_path)
    assert entries == []
