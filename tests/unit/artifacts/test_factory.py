from pathlib import Path
from typing import Any

import app.artifacts.storage as storage_module
from app.artifacts.storage import LocalArtifactStore, S3ArtifactStore, build_artifact_store
from app.core.config import Settings


def test_factory_builds_local_store_and_creates_root(tmp_path: Path) -> None:
    root = tmp_path / "nested" / "artifacts"

    store = build_artifact_store(Settings(_env_file=None, artifact_root=root))

    assert isinstance(store, LocalArtifactStore)
    assert root.is_dir()


def test_factory_builds_s3_store_without_exposing_secrets(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def recording_client(service_name: str, **kwargs: Any) -> object:
        captured["service_name"] = service_name
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(storage_module.boto3, "client", recording_client)
    settings = Settings(
        _env_file=None,
        artifact_backend="s3",
        artifact_s3_bucket="evalops",
        artifact_s3_prefix="objects/v1",
        artifact_s3_endpoint_url="http://minio:9000",
        artifact_s3_region="us-east-1",
        artifact_s3_access_key_id="access-key",
        artifact_s3_secret_access_key="secret-key",
        artifact_s3_addressing_style="path",
    )

    store = build_artifact_store(settings)

    assert isinstance(store, S3ArtifactStore)
    assert captured["service_name"] == "s3"
    assert captured["endpoint_url"] == "http://minio:9000"
    assert captured["region_name"] == "us-east-1"
    assert captured["aws_access_key_id"] == "access-key"
    assert captured["aws_secret_access_key"] == "secret-key"
    assert captured["config"].s3 == {"addressing_style": "path"}
    assert "secret-key" not in repr(settings)
