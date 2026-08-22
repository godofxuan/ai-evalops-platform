import json
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


def test_s3_artifact_settings_preserve_secrets_and_require_bucket(monkeypatch) -> None:
    monkeypatch.setenv("EVALOPS_ARTIFACT_BACKEND", "s3")
    monkeypatch.setenv("EVALOPS_ARTIFACT_S3_BUCKET", "evalops")
    monkeypatch.setenv("EVALOPS_ARTIFACT_S3_ACCESS_KEY_ID", "minio-access")
    monkeypatch.setenv("EVALOPS_ARTIFACT_S3_SECRET_ACCESS_KEY", "minio-secret")

    settings = Settings(_env_file=None)

    assert settings.artifact_backend == "s3"
    assert settings.artifact_s3_bucket == "evalops"
    assert settings.artifact_s3_access_key_id is not None
    assert settings.artifact_s3_access_key_id.get_secret_value() == "minio-access"
    assert settings.artifact_s3_secret_access_key is not None
    assert settings.artifact_s3_secret_access_key.get_secret_value() == "minio-secret"
    assert "minio-secret" not in repr(settings)


def test_s3_artifact_backend_requires_bucket() -> None:
    with pytest.raises(ValidationError, match="artifact S3 bucket"):
        Settings(_env_file=None, artifact_backend="s3")


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


def test_database_reconnect_delay_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="database reconnect base delay"):
        Settings(
            _env_file=None,
            database_reconnect_base_seconds=5,
            database_reconnect_max_seconds=1,
        )


def test_outbox_dispatch_settings_have_bounded_operational_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.outbox_poll_seconds == 0.5
    assert settings.outbox_batch_size == 50
    assert settings.outbox_lease_seconds == 30
    assert settings.outbox_publish_timeout_seconds == 5
    assert settings.outbox_retry_base_seconds == 1
    assert settings.outbox_retry_max_seconds == 60


def test_outbox_cleanup_settings_have_bounded_operational_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.outbox_retention_seconds == 7 * 24 * 60 * 60
    assert settings.outbox_cleanup_interval_seconds == 60
    assert settings.outbox_cleanup_batch_size == 500


def test_audit_dispatcher_settings_have_bounded_operational_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.audit_dispatcher_poll_seconds == 0.5
    assert settings.audit_dispatcher_batch_size == 50
    assert settings.audit_dispatcher_lease_seconds == 30
    assert settings.audit_dispatcher_delivery_timeout_seconds == 5
    assert settings.audit_dispatcher_retry_base_seconds == 1
    assert settings.audit_dispatcher_retry_max_seconds == 60
    assert settings.audit_dispatcher_metrics_port == 9103


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "audit_dispatcher_delivery_timeout_seconds": 30,
            "audit_dispatcher_lease_seconds": 30,
        },
        {
            "audit_dispatcher_retry_base_seconds": 61,
            "audit_dispatcher_retry_max_seconds": 60,
        },
    ],
)
def test_audit_dispatcher_settings_reject_unsafe_cross_field_timing(
    overrides: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"outbox_publish_timeout_seconds": 30, "outbox_lease_seconds": 30},
        {"outbox_retry_base_seconds": 61, "outbox_retry_max_seconds": 60},
    ],
)
def test_outbox_dispatch_settings_reject_unsafe_cross_field_timing(
    overrides: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_observability_settings_have_safe_bounded_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.metrics_enabled is True
    assert settings.metrics_host == "0.0.0.0"
    assert settings.worker_metrics_port == 9101
    assert settings.reaper_metrics_port == 9102
    assert settings.audit_dispatcher_metrics_port == 9103
    assert settings.otel_enabled is True
    assert settings.otel_service_name == "ai-evalops-platform"
    assert settings.otel_exporter_otlp_endpoint is None


def test_settings_load_operator_http_target_registry(monkeypatch) -> None:
    registry = {
        "rag-production": {
            "version": "rag-v1",
            "config": {
                "base_url": "https://rag.example.com",
                "endpoint": "/v1/query",
                "auth_env_var": "RAG_PRODUCTION_TOKEN",
            },
        }
    }
    monkeypatch.setenv("EVALOPS_HTTP_TARGET_REGISTRY", json.dumps(registry))

    settings = Settings(_env_file=None)

    assert settings.http_target_registry == registry


def test_settings_accept_registry_without_redundant_allowed_hosts() -> None:
    settings = Settings(
        _env_file=None,
        http_target_registry={
            "rag-production": {
                "version": "rag-v1",
                "config": {
                    "base_url": "https://rag.example.com",
                    "endpoint": "/v1/query",
                },
            }
        },
    )

    assert "allowed_hosts" not in settings.http_target_registry["rag-production"]["config"]


def test_settings_reject_registry_supplied_allowed_hosts() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            http_target_registry={
                "rag-production": {
                    "version": "rag-v1",
                    "config": {
                        "base_url": "https://rag.example.com",
                        "endpoint": "/v1/query",
                        "allowed_hosts": ["rag.example.com"],
                    },
                }
            },
        )


def test_settings_reject_unknown_http_target_registry_entry_fields() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            http_target_registry={
                "rag-production": {
                    "version": "rag-v1",
                    "config": {
                        "base_url": "https://rag.example.com",
                        "endpoint": "/v1/query",
                    },
                    "follow_redirects": True,
                }
            },
        )


def test_settings_registry_validation_error_hides_plaintext_secret() -> None:
    secret = "operator-accidentally-pasted-secret"

    with pytest.raises(ValidationError) as caught:
        Settings(
            _env_file=None,
            http_target_registry={
                "rag-production": {
                    "version": "rag-v1",
                    "config": {
                        "base_url": "https://rag.example.com",
                        "endpoint": "/v1/query",
                        "authentication": {"bearer": secret},
                    },
                }
            },
        )

    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


def test_settings_reject_http_target_registry_without_version() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            http_target_registry={
                "rag-production": {
                    "version": "",
                    "config": {
                        "base_url": "https://rag.example.com",
                        "endpoint": "/v1/query",
                    },
                }
            },
        )


def test_settings_reject_http_target_registry_without_execution_config() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            http_target_registry={
                "rag-production": {
                    "version": "rag-v1",
                }
            },
        )


def test_settings_reject_unsafe_http_target_registry_url() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            http_target_registry={
                "rag-production": {
                    "version": "rag-v1",
                    "config": {
                        "base_url": "http://rag.example.com",
                        "endpoint": "/v1/query",
                    },
                }
            },
        )
