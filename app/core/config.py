from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EVALOPS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr = Field(
        default_factory=lambda: SecretStr(
            "postgresql+psycopg://evalops:evalops@localhost:5432/evalops"
        )
    )
    redis_url: SecretStr = Field(default_factory=lambda: SecretStr("redis://localhost:6379/0"))
    artifact_backend: Literal["local", "s3"] = "local"
    artifact_root: Path = Path("data/artifacts")
    artifact_s3_bucket: str | None = None
    artifact_s3_prefix: str = "artifacts/v1"
    artifact_s3_endpoint_url: str | None = None
    artifact_s3_region: str = "us-east-1"
    artifact_s3_access_key_id: SecretStr | None = None
    artifact_s3_secret_access_key: SecretStr | None = None
    artifact_s3_addressing_style: Literal["path", "virtual"] = "path"
    alembic_config_path: Path = Path("alembic.ini")
    readiness_timeout_seconds: float = Field(default=2.0, gt=0.0, le=30.0)
    database_reconnect_base_seconds: float = Field(default=0.5, gt=0, le=300)
    database_reconnect_max_seconds: float = Field(default=30.0, gt=0, le=3_600)
    database_reconnect_jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    dataset_max_file_bytes: int = Field(
        default=10 * 1024 * 1024,
        gt=0,
        le=100 * 1024 * 1024,
    )
    dataset_max_cases: int = Field(default=10_000, gt=0, le=100_000)
    dataset_max_line_bytes: int = Field(
        default=1024 * 1024,
        gt=0,
        le=10 * 1024 * 1024,
    )
    worker_lease_seconds: int = Field(default=30, ge=5, le=3_600)
    worker_heartbeat_seconds: int = Field(default=10, ge=1, le=1_200)
    worker_claim_batch_size: int = Field(default=1, ge=1, le=100)
    worker_poll_seconds: float = Field(default=0.5, gt=0, le=60)
    reaper_interval_seconds: float = Field(default=5.0, gt=0, le=300)
    reaper_batch_size: int = Field(default=100, ge=1, le=1_000)
    outbox_poll_seconds: float = Field(default=0.5, gt=0, le=60)
    outbox_batch_size: int = Field(default=50, ge=1, le=1_000)
    outbox_lease_seconds: float = Field(default=30, gt=0, le=3_600)
    outbox_publish_timeout_seconds: float = Field(default=5, gt=0, le=30)
    outbox_retry_base_seconds: float = Field(default=1, gt=0, le=300)
    outbox_retry_max_seconds: float = Field(default=60, gt=0, le=3_600)
    outbox_retention_seconds: int = Field(default=7 * 24 * 60 * 60, ge=3_600, le=31_536_000)
    outbox_cleanup_interval_seconds: float = Field(default=60, gt=0, le=3_600)
    outbox_cleanup_batch_size: int = Field(default=500, ge=1, le=10_000)
    retry_base_delay_seconds: float = Field(default=1.0, gt=0, le=300)
    retry_max_delay_seconds: float = Field(default=60.0, gt=0, le=3_600)
    retry_jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0, le=300)
    sse_fallback_poll_seconds: float = Field(default=2.0, gt=0, le=300)
    metrics_enabled: bool = True
    metrics_host: str = "0.0.0.0"
    worker_metrics_port: int = Field(default=9101, ge=1, le=65_535)
    reaper_metrics_port: int = Field(default=9102, ge=1, le=65_535)
    otel_enabled: bool = True
    otel_service_name: str = Field(
        default="ai-evalops-platform",
        min_length=1,
        max_length=128,
    )
    otel_exporter_otlp_endpoint: str | None = None
    otel_exporter_otlp_headers: SecretStr | None = None
    mcp_api_key: SecretStr | None = None
    http_target_registry: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)

    @field_validator("http_target_registry")
    @classmethod
    def validate_http_target_registry_versions(
        cls,
        registry: dict[str, dict[str, JsonValue]],
    ) -> dict[str, dict[str, JsonValue]]:
        from app.targets.base import InvalidTargetConfiguration
        from app.targets.http_rag import build_registered_http_target_config

        for target_id, entry in registry.items():
            if set(entry) - {"version", "config"}:
                raise ValueError("HTTP target registry entries contain unknown fields")
            version = entry.get("version")
            if not isinstance(version, str) or not 1 <= len(version) <= 128:
                raise ValueError("HTTP target registry entries require a bounded version")
            config = entry.get("config")
            if not isinstance(config, dict):
                raise ValueError("HTTP target registry entries require an execution config")
            try:
                build_registered_http_target_config(target_id, config)
            except InvalidTargetConfiguration as error:
                raise ValueError("HTTP target registry contains an unsafe config") from error
        return registry

    @model_validator(mode="after")
    def validate_worker_timing(self) -> "Settings":
        if self.worker_heartbeat_seconds >= self.worker_lease_seconds:
            raise ValueError("worker heartbeat interval must be shorter than lease")
        if self.database_reconnect_base_seconds > self.database_reconnect_max_seconds:
            raise ValueError("database reconnect base delay must not exceed maximum delay")
        if self.retry_base_delay_seconds > self.retry_max_delay_seconds:
            raise ValueError("retry base delay must not exceed maximum delay")
        if self.outbox_retry_base_seconds > self.outbox_retry_max_seconds:
            raise ValueError("outbox retry base delay must not exceed maximum delay")
        if self.outbox_publish_timeout_seconds >= self.outbox_lease_seconds:
            raise ValueError("outbox publish timeout must be shorter than lease")
        if self.artifact_backend == "s3" and not self.artifact_s3_bucket:
            raise ValueError("artifact S3 bucket is required for the S3 backend")
        if (self.artifact_s3_access_key_id is None) != (self.artifact_s3_secret_access_key is None):
            raise ValueError("artifact S3 access and secret keys must be configured together")
        return self
