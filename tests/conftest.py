import asyncio
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from app.core.event_loop import create_psycopg_compatible_event_loop
from scripts.gate1_prepared_evidence import KEY_EXECUTION_SCRIPT_PATHS

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def pytest_asyncio_loop_factories(
    config: pytest.Config,
    item: pytest.Item,
) -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    del config, item
    return {"psycopg-compatible": create_psycopg_compatible_event_loop}


@pytest.fixture
def clean_gate1_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    source_paths = (
        "Dockerfile",
        ".dockerignore",
        ".gitignore",
        "pyproject.toml",
        "uv.lock",
        "deploy/compose.yaml",
        "scripts/worker_scaling_protocol.md",
        *KEY_EXECUTION_SCRIPT_PATHS,
    )
    for source_path in source_paths:
        destination = repository / source_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT_ROOT / source_path, destination)
    (repository / "app").mkdir()
    (repository / "app" / "__init__.py").write_text("", encoding="utf-8")

    git_prefix = [
        "git",
        "-c",
        f"safe.directory={repository}",
        "-C",
        str(repository),
    ]
    subprocess.run([*git_prefix, "init"], check=True, capture_output=True)
    subprocess.run(
        [*git_prefix, "config", "user.email", "gate1-tests@example.invalid"],
        check=True,
    )
    subprocess.run(
        [*git_prefix, "config", "user.name", "Gate 1 Tests"],
        check=True,
    )
    subprocess.run([*git_prefix, "add", "."], check=True)
    subprocess.run(
        [*git_prefix, "commit", "-m", "prepared evidence source"],
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(repository)
    return repository
