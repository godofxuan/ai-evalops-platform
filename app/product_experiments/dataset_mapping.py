"""Versioned product-to-core dataset mapping; labels remain evaluator-only metadata."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Literal

from app.datasets.validation import ValidatedJSONL, validate_jsonl
from app.product_experiments.runner import parse_product_dataset


@dataclass(frozen=True, slots=True)
class MappedProductDataset:
    source_sha256: str
    dataset: ValidatedJSONL
    mapping_version: Literal["evalops.product-dataset-mapping/1.0"] = (
        "evalops.product-dataset-mapping/1.0"
    )


def map_product_dataset(payload: bytes, *, expected_sha256: str) -> MappedProductDataset:
    cases = parse_product_dataset(payload, expected_sha256=expected_sha256)
    lines: list[bytes] = []
    for case in cases:
        metadata: dict[str, Any] = {
            "evalops_product_case": case.model_dump(mode="json", exclude_unset=True)
        }
        if "public_context" in case.metadata:
            metadata["public_context"] = copy.deepcopy(case.metadata["public_context"])
        record = {
            "case_id": case.case_id,
            "question": case.prompt,
            "expected_answer": case.reference_answer,
            "metadata": metadata,
        }
        lines.append(
            json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        )
    dataset = validate_jsonl(b"\n".join(lines) + b"\n")
    return MappedProductDataset(source_sha256=expected_sha256, dataset=dataset)
