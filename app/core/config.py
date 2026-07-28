from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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
    artifact_root: Path = Path("data/artifacts")
    alembic_config_path: Path = Path("alembic.ini")
    readiness_timeout_seconds: float = Field(default=2.0, gt=0.0, le=30.0)
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
