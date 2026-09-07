"""Validate frozen local inputs without reading paths or contacting targets.

Raw spec/policy hashes identify unavailable original bytes; this checks normalized
content and result bindings, not independent provenance or original-byte recovery.
"""

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.external_harness.formal_quality import FormalQualityPolicy
from app.external_harness.harness_envelope import canonical_sha256
from app.product_experiments.spec import ExperimentSpec

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ExperimentInputSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["evalops.experiment-input-snapshot/1.0"]
    spec_sha256: Digest
    dataset_sha256: Digest
    policy_sha256: Digest
    configuration: dict[str, Any]
    policy: dict[str, Any]
    content_sha256: Digest

    def validate_result_binding(self, result: dict[str, Any]) -> None:
        configuration = self.configuration
        expected_keys = set(ExperimentSpec.model_fields) - {"experiment_id", "policy_path"}
        if set(configuration) != expected_keys:
            raise ValueError("snapshot configuration fields differ from its version")
        if self.dataset_sha256 != result["dataset_sha256"] or configuration["dataset"] != {
            "sha256": self.dataset_sha256
        }:
            raise ValueError("snapshot dataset identity mismatch")
        if self.content_sha256 != canonical_sha256(
            {"configuration": configuration, "policy": self.policy}
        ):
            raise ValueError("snapshot content digest mismatch")
        # These synthetic paths restore the existing schema only. Never load them.
        payload = {
            **configuration,
            "experiment_id": "snapshot-validation",
            "policy_path": "not-read",
            "dataset": {"path": "not-read", "sha256": self.dataset_sha256},
        }
        spec = ExperimentSpec.model_validate_json(json.dumps(payload, allow_nan=False))
        FormalQualityPolicy.model_validate_json(json.dumps(self.policy, allow_nan=False))
        if spec.scope != result["scope"] or spec.task_type != result["task_type"]:
            raise ValueError("snapshot scope or task identity mismatch")
        expected_sources = {
            arm.label: {
                "repository": arm.source_repository,
                "sha": arm.source_sha,
                "provider_type": arm.provider.type,
            }
            for arm in spec.arms
        }
        if expected_sources != result["source_identities"]:
            raise ValueError("snapshot source identities mismatch")
