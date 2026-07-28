from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_load_prefixed_environment_without_exposing_secret_urls(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = "postgresql+psycopg://evalops:database-secret@db:5432/evalops"
    redis_url = "redis://:redis-secret@redis:6379/0"
    monkeypatch.setenv("EVALOPS_DATABASE_URL", database_url)
    monkeypatch.setenv("EVALOPS_REDIS_URL", redis_url)
    monkeypatch.setenv("EVALOPS_ARTIFACT_ROOT", str(tmp_path))

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value() == database_url
    assert settings.redis_url.get_secret_value() == redis_url
    assert settings.artifact_root == tmp_path
    assert "database-secret" not in repr(settings)
    assert "redis-secret" not in repr(settings)


def test_settings_expose_bounded_dataset_upload_limits(monkeypatch) -> None:
    monkeypatch.setenv("EVALOPS_DATASET_MAX_FILE_BYTES", "2048")
    monkeypatch.setenv("EVALOPS_DATASET_MAX_CASES", "12")
    monkeypatch.setenv("EVALOPS_DATASET_MAX_LINE_BYTES", "512")

    settings = Settings(_env_file=None)

    assert settings.dataset_max_file_bytes == 2048
    assert settings.dataset_max_cases == 12
    assert settings.dataset_max_line_bytes == 512


def test_worker_heartbeat_must_be_shorter_than_lease() -> None:
    with pytest.raises(ValidationError, match="heartbeat interval"):
        Settings(
            _env_file=None,
            worker_lease_seconds=10,
            worker_heartbeat_seconds=10,
        )
