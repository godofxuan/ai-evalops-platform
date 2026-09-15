"""Versioned source identity matching; deliberately not semantic entailment."""

from collections.abc import Mapping, Sequence

from app.targets.base import TargetInvalidResponseError

LEGACY_SCORER = "evalops.citation-scorer/1.0"
CURRENT_SCORER = "evalops.citation-scorer/2.0"


def validate_scorer_version(version: str) -> None:
    if version not in {LEGACY_SCORER, CURRENT_SCORER}:
        raise ValueError("unsupported citation scorer version")


def canonical_citation_id(citation: Mapping[str, object], *, schema_version: str) -> str | None:
    validate_scorer_version(schema_version)
    if schema_version == LEGACY_SCORER:
        value = citation.get("source_id", citation.get("id"))
        return value if isinstance(value, str) and value else None
    values = [citation[key] for key in ("source_id", "id") if key in citation]
    if not values:
        return None  # Unresolved references contribute to the precision denominator.
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise TargetInvalidResponseError("target_citation_invalid")
    if len(values) == 2 and values[0] != values[1]:
        raise TargetInvalidResponseError("target_citation_invalid")
    value = values[0]
    assert isinstance(value, str)
    return value  # Never trim, coerce or choose the more favorable alias.


def validate_citations(
    citations: Sequence[Mapping[str, object]], *, scorer_version: str = CURRENT_SCORER
) -> None:
    validate_scorer_version(scorer_version)
    for citation in citations:
        canonical_citation_id(citation, schema_version=scorer_version)


def scorer_for_result(schema_version: str) -> str:
    if schema_version in {"evalops.experiment-result/1.0", "evalops.experiment-result/2.0"}:
        return LEGACY_SCORER
    if schema_version == "evalops.experiment-result/3.0":
        return CURRENT_SCORER
    raise ValueError("unsupported experiment result version")
