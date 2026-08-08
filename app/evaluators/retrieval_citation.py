from typing import Any

from app.domain.evaluation import EvaluationCase, EvaluationResult, TargetResult


class RetrievalCitationEvaluator:
    """Deterministic retrieval/citation overlap against explicit source labels."""

    def evaluate(
        self,
        case: EvaluationCase,
        target_result: TargetResult,
        *,
        attempt_number: int,
    ) -> EvaluationResult:
        del attempt_number
        relevant = _labeled_ids(case.metadata.get("relevant_source_ids"))
        if relevant is None:
            return EvaluationResult(
                metrics={
                    "retrieval_recall": None,
                    "citation_precision": None,
                    "citation_recall": None,
                    "citation_f1": None,
                }
            )

        retrieved = _object_ids(target_result.sources, keys=("id", "source_id"))
        cited = _object_ids(target_result.citations, keys=("source_id", "id"))
        retrieval_recall = len(retrieved & relevant) / len(relevant)
        citation_matches = len(cited & relevant)
        citation_precision = citation_matches / len(cited) if cited else 0.0
        citation_recall = citation_matches / len(relevant)
        citation_f1 = (
            0.0
            if citation_precision + citation_recall == 0
            else 2 * citation_precision * citation_recall / (citation_precision + citation_recall)
        )
        return EvaluationResult(
            metrics={
                "retrieval_recall": retrieval_recall,
                "citation_precision": citation_precision,
                "citation_recall": citation_recall,
                "citation_f1": citation_f1,
            }
        )


def _labeled_ids(value: Any) -> set[str] | None:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        return None
    return {item for item in value if isinstance(item, str)}


def _object_ids(values: tuple[dict[str, Any], ...], *, keys: tuple[str, ...]) -> set[str]:
    identifiers: set[str] = set()
    for value in values:
        for key in keys:
            identifier = value.get(key)
            if isinstance(identifier, str) and identifier.strip():
                identifiers.add(identifier)
                break
    return identifiers
