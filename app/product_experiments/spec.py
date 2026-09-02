"""Strict declarative contract for a paired RAG or Agent experiment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DatasetReference(_StrictModel):
    path: str = Field(min_length=1, max_length=1_024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FixtureProviderSpec(_StrictModel):
    type: Literal["fixture"]
    profile: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")


class HTTPProviderSpec(_StrictModel):
    type: Literal["http"]
    target_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
    )
    base_url: str = Field(min_length=1, max_length=2_048)
    endpoint: str = Field(min_length=1, max_length=1_024)
    auth_env_var: str | None = Field(
        default=None,
        pattern=r"^[A-Z][A-Z0-9_]{0,127}$",
    )
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    request_question_field: str = Field(default="question", min_length=1, max_length=100)
    answer_path: str = Field(default="answer", min_length=1, max_length=200)
    citations_path: str = Field(default="citations", min_length=1, max_length=200)
    sources_path: str = Field(default="sources", min_length=1, max_length=200)
    trace_path: str = Field(default="trace", min_length=1, max_length=200)
    usage_path: str = Field(default="usage", min_length=1, max_length=200)
    include_metadata: bool = False


ProviderSpec = Annotated[FixtureProviderSpec | HTTPProviderSpec, Field(discriminator="type")]


class ExperimentArm(_StrictModel):
    label: Literal["baseline", "candidate"]
    source_repository: str = Field(min_length=1, max_length=500)
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    provider: ProviderSpec


class ExperimentSpec(_StrictModel):
    schema_version: Literal["evalops.experiment/1.0"]
    experiment_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
    )
    scope: Literal["DEMO", "FORMAL"]
    dataset: DatasetReference
    policy_path: str = Field(min_length=1, max_length=1_024)
    arms: tuple[ExperimentArm, ExperimentArm]
    evaluators: tuple[Literal["reference_answer", "citation_correctness", "tool_error_rate"], ...]
    max_concurrency: int = Field(default=8, ge=1, le=64)

    @model_validator(mode="after")
    def validate_pair_and_evaluators(self) -> ExperimentSpec:
        if [arm.label for arm in self.arms] != ["baseline", "candidate"]:
            raise ValueError("arms must contain baseline and candidate in that order")
        required = {"reference_answer", "citation_correctness", "tool_error_rate"}
        if set(self.evaluators) != required or len(self.evaluators) != len(required):
            raise ValueError(f"evaluators must contain exactly {sorted(required)}")
        return self


@dataclass(frozen=True, slots=True)
class LoadedExperimentSpec:
    spec_path: Path
    spec: ExperimentSpec
    dataset_path: Path
    policy_path: Path


def load_experiment_spec(path: Path) -> LoadedExperimentSpec:
    resolved = path.resolve()
    spec = ExperimentSpec.model_validate_json(resolved.read_text(encoding="utf-8"))
    return LoadedExperimentSpec(
        spec_path=resolved,
        spec=spec,
        dataset_path=(resolved.parent / spec.dataset.path).resolve(),
        policy_path=(resolved.parent / spec.policy_path).resolve(),
    )


__all__ = [
    "ExperimentArm",
    "ExperimentSpec",
    "FixtureProviderSpec",
    "HTTPProviderSpec",
    "LoadedExperimentSpec",
    "load_experiment_spec",
]
