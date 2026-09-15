"""Prepare an existing DEMO benchmark for the durable client, using registered targets only."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.core.strict_json import decode_evidence_json
from app.datasets.schemas import DatasetCreate, DatasetVersionRead
from app.external_harness.formal_quality import FormalQualityPolicy
from app.product_experiments.client import ProductAPIClient, ProductAPIError
from app.product_experiments.dataset_mapping import map_product_dataset
from app.product_experiments.spec import load_experiment_spec, read_bounded_config
from app.product_experiments.submission import DurableExperimentRequest, RegisteredExperimentArm


class TargetPair(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    baseline: RegisteredExperimentArm
    candidate: RegisteredExperimentArm


async def prepare_dataset(
    client: ProductAPIClient,
    *,
    raw_dataset: bytes,
    expected_sha256: str,
    output_dir: Path,
    name: str,
) -> DatasetVersionRead:
    """No automatic retries. Partial receipts remain if upload or networking fails."""
    mapped = map_product_dataset(raw_dataset, expected_sha256=expected_sha256)
    DatasetCreate(name=name)  # Validate before the first remote mutation.
    await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=False)
    (output_dir / "cases.json").write_bytes(raw_dataset)
    (output_dir / "normalized.jsonl").write_bytes(mapped.dataset.content)
    (output_dir / "mapping.json").write_text(
        json.dumps(
            {
                "source_dataset_sha256": expected_sha256,
                "normalized_dataset_sha256": mapped.dataset.sha256,
                "case_count": mapped.dataset.case_count,
                "mapping_version": mapped.mapping_version,
                "visibility": "PRIVATE_CONTROLLED_INPUT",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    dataset = await client.create_dataset(name=name)
    (output_dir / "dataset.json").write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
    version = await client.upload_dataset_version(dataset.id, mapped.dataset.content)
    (output_dir / "dataset-version.json").write_text(
        version.model_dump_json(indent=2), encoding="utf-8"
    )
    if version.case_count != mapped.dataset.case_count:
        raise ProductAPIError("api_dataset_case_count")
    return version


async def _run(args: argparse.Namespace) -> int:
    loaded = load_experiment_spec(args.spec)
    spec = loaded.spec
    if spec.scope != "DEMO":
        raise ValueError("demo_scope_required")
    policy_bytes = read_bounded_config(loaded.policy_path)
    decode_evidence_json(policy_bytes)
    policy = FormalQualityPolicy.model_validate_json(policy_bytes)
    with loaded.dataset_path.open("rb") as stream:
        raw = stream.read(10 * 1024 * 1024 + 1)
    mapped = map_product_dataset(raw, expected_sha256=spec.dataset.sha256)
    if not args.targets or not args.api_url or not os.getenv("EVALOPS_API_KEY"):
        print(
            json.dumps(
                {
                    "status": "NEEDS_REGISTERED_TARGET",
                    "required_inputs": [
                        "--api-url",
                        "--targets with actual registered IDs/version/source pins",
                        "EVALOPS_API_KEY",
                    ],
                    "source_dataset_sha256": hashlib.sha256(raw).hexdigest(),
                    "normalized_dataset_sha256": mapped.dataset.sha256,
                    "case_count": mapped.dataset.case_count,
                    "remote_mutations": 0,
                }
            )
        )
        return 2
    target_bytes = read_bounded_config(args.targets)
    decode_evidence_json(target_bytes)
    targets = TargetPair.model_validate_json(target_bytes)
    async with ProductAPIClient(args.api_url, os.environ["EVALOPS_API_KEY"]) as client:
        version = await prepare_dataset(
            client,
            raw_dataset=raw,
            expected_sha256=spec.dataset.sha256,
            output_dir=args.output_dir,
            name=spec.experiment_id,
        )
    request = DurableExperimentRequest(
        schema_version="evalops.durable-experiment-request/1.0",
        experiment_id=spec.experiment_id,
        task_type=spec.task_type,
        dataset_version_id=version.id,
        source_dataset_sha256=spec.dataset.sha256,
        baseline=targets.baseline,
        candidate=targets.candidate,
        policy=policy,
        agent_comparison_policy=spec.agent_comparison_policy,
        citation_precision_min=spec.citation_precision_min,
        max_observation_bytes=spec.max_observation_bytes,
        execution_timeout_seconds=spec.execution_timeout_seconds,
    )
    (args.output_dir / "request.json").write_text(
        request.model_dump_json(indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "DATASET_READY_NOT_SUBMITTED",
                "dataset_id": str(version.dataset_id),
                "dataset_version_id": str(version.id),
                "source_dataset_sha256": spec.dataset.sha256,
                "normalized_dataset_sha256": version.sha256,
            }
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--api-url", default=os.getenv("EVALOPS_API_URL"))
    parser.add_argument("--targets", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New controlled PRIVATE directory. Never publish real input or credentials.",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except ProductAPIError as error:
        print(
            json.dumps(
                {
                    "status": "PREPARATION_FAILED",
                    "error_code": str(error),
                    "retry": "NO_AUTOMATIC_RETRY; inspect partial dataset receipts first.",
                }
            )
        )
        return 2
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "status": "PREPARATION_FAILED",
                    "error_code": "demo_input_or_output_invalid",
                    "retry": "NO_AUTOMATIC_RETRY; preserve partial receipts.",
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
