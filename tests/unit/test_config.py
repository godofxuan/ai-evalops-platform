from pathlib import Path

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
