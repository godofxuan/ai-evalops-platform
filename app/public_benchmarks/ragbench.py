"""Frozen RAGBench sampling and descriptive calibration, without model execution."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.reviews.agreement import calculate_agreement

DATASET = "galileo-ai/ragbench"
REVISION = "97808f3e5fd16ede40bbff6c2949af8139b2eb7b"
DOMAINS = ("hotpotqa", "finqa", "techqa")
PREDICTION_COLUMNS = ("gpt3_adherence", "ragas_faithfulness", "trulens_groundedness")
SAMPLING_RULE = (
    "One response per source question: smallest sha256(revision/domain/id/generation_model_name); "
    "then 100 question IDs per domain by ascending sha256(revision/domain/id); no label filtering"
)


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def select_pilot(
    rows_by_domain: Mapping[str, Sequence[dict[str, Any]]], *, per_domain: int = 100
) -> list[dict[str, Any]]:
    """Select by source identity only; never drop invalid labels or missing predictions."""
    if type(per_domain) is not int or not 1 <= per_domain <= 1000:
        raise ValueError("per_domain must be between 1 and 1000")
    selected: list[dict[str, Any]] = []
    for domain, rows in sorted(rows_by_domain.items()):
        if domain not in DOMAINS or len(rows) < per_domain:
            raise ValueError("Unsupported domain or insufficient source rows")
        identities: set[tuple[str, str]] = set()
        representatives: dict[str, tuple[str, dict[str, Any]]] = {}
        ranked: list[tuple[str, dict[str, Any]]] = []
        for item in rows:
            identifier = item.get("id")
            model = item.get("generation_model_name")
            if not isinstance(identifier, str) or not identifier or not isinstance(model, str):
                raise ValueError(
                    "Source question and generation-model IDs must be nonempty strings"
                )
            if (identifier, model) in identities:
                raise ValueError("Source question/model identities must be unique")
            identities.add((identifier, model))
            response_hash = hashlib.sha256(
                f"{REVISION}/{domain}/{identifier}/{model}".encode()
            ).hexdigest()
            if identifier not in representatives or response_hash < representatives[identifier][0]:
                representatives[identifier] = (response_hash, item)
        if len(representatives) < per_domain:
            raise ValueError("Insufficient distinct source questions")
        for identifier, (_response_hash, item) in representatives.items():
            digest = hashlib.sha256(f"{REVISION}/{domain}/{identifier}".encode()).hexdigest()
            ranked.append((digest, item))
        for digest, item in sorted(ranked, key=lambda pair: pair[0])[:per_domain]:
            for key in ("question", "response"):
                if not isinstance(item.get(key), str) or not item[key].strip():
                    raise ValueError(f"Selected row has invalid {key}; do not replace the row")
            documents = item.get("documents")
            if (
                not isinstance(documents, list)
                or not documents
                or any(
                    not isinstance(document, str) or not document.strip() for document in documents
                )
            ):
                raise ValueError("Selected row has invalid documents; do not replace the row")
            selected.append(
                {
                    "case_id": f"ragbench/{domain}/test/{item['id']}",
                    "source_id": item["id"],
                    "domain": domain,
                    "split": "test",
                    "source_revision": REVISION,
                    "sampling_hash": digest,
                    "question": item["question"],
                    "documents": list(documents),
                    "response": item["response"],
                    "adherence_score": item.get("adherence_score"),
                    "annotating_model_name": item.get("annotating_model_name"),
                    "generation_model_name": item.get("generation_model_name"),
                    "label_origin": "PUBLIC_AUTOMATED_ANNOTATION",
                    "published_predictions": {
                        column: item.get(column) for column in PREDICTION_COLUMNS
                    },
                }
            )
    return selected


def calibration_metrics(
    cases: Sequence[dict[str, Any]], predictions: Mapping[str, object], *, threshold: float = 0.5
) -> dict[str, Any]:
    """Compare supplied scores to public automatic labels; absent data never becomes zero."""
    if isinstance(threshold, bool) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Invalid threshold")
    identities = [item["case_id"] for item in cases]
    if any(not isinstance(identity, str) for identity in identities) or len(set(identities)) != len(
        identities
    ):
        raise ValueError("Case identities must be unique strings")
    if set(predictions) - set(identities):
        raise ValueError("Unknown prediction case ID")
    pairs: list[tuple[bool, bool]] = []
    missing = invalid = invalid_reference = 0
    for item in cases:
        reference = item.get("adherence_score")
        score = predictions.get(item["case_id"])
        reference_valid = type(reference) is bool
        if not reference_valid:
            invalid_reference += 1
        if score is None:
            missing += 1
        elif not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            invalid += 1
        elif isinstance(reference, bool):
            pairs.append((reference, score >= threshold))
    true_supported = sum(reference and prediction for reference, prediction in pairs)
    true_unsupported = sum(not reference and not prediction for reference, prediction in pairs)
    false_supported = sum(not reference and prediction for reference, prediction in pairs)
    false_unsupported = sum(reference and not prediction for reference, prediction in pairs)
    positive = true_supported + false_unsupported
    negative = true_unsupported + false_supported
    agreement = calculate_agreement(pairs)
    return {
        "case_count": len(cases),
        "paired_count": len(pairs),
        "paired_coverage": len(pairs) / len(cases) if cases else None,
        "missing_prediction_count": missing,
        "invalid_prediction_count": invalid,
        "invalid_reference_count": invalid_reference,
        "accuracy": agreement.exact_agreement,
        "cohen_kappa": agreement.cohen_kappa,
        "balanced_accuracy": (true_supported / positive + true_unsupported / negative) / 2
        if positive and negative
        else None,
        "false_supported_rate": false_supported / negative if negative else None,
        "supported_f1": 2
        * true_supported
        / (2 * true_supported + false_supported + false_unsupported)
        if 2 * true_supported + false_supported + false_unsupported
        else None,
        "confusion": {
            "true_supported": true_supported,
            "true_unsupported": true_unsupported,
            "false_supported": false_supported,
            "false_unsupported": false_unsupported,
        },
        "threshold": threshold,
        "label_origin": "PUBLIC_AUTOMATED_ANNOTATION",
        "human_agreement_claim_allowed": False,
        "production_quality_claim_allowed": False,
    }


def published_prediction_report(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups = {"all": list(cases)}
    groups.update(
        {domain: [item for item in cases if item["domain"] == domain] for domain in DOMAINS}
    )
    return {
        "status": "PUBLISHED_PREDICTIONS_OFFLINE_RESCORING",
        "model_calls": 0,
        "threshold_policy": "fixed >= 0.5, declared before scoring; not tuned on test labels",
        "groups": {
            name: {
                column: calibration_metrics(
                    items,
                    {item["case_id"]: item["published_predictions"].get(column) for item in items},
                )
                for column in PREDICTION_COLUMNS
            }
            for name, items in groups.items()
        },
    }
