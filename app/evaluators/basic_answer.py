import re
import unicodedata

from app.domain.evaluation import EvaluationCase, EvaluationResult, TargetResult


def _normalize_lexical_answer(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


class BasicAnswerEvaluator:
    """Lexical signals only; these metrics are not semantic correctness."""

    def evaluate(
        self,
        case: EvaluationCase,
        target_result: TargetResult,
        *,
        attempt_number: int,
    ) -> EvaluationResult:
        del attempt_number
        answer = target_result.answer
        expected = case.expected_answer if isinstance(case.expected_answer, str) else None
        normalized_answer = None if answer is None else _normalize_lexical_answer(answer)
        normalized_expected = None if expected is None else _normalize_lexical_answer(expected)
        keyword_coverage = _keyword_coverage(
            normalized_answer=normalized_answer,
            metadata=case.metadata,
        )
        return EvaluationResult(
            metrics={
                "lexical_exact_match": (
                    answer == expected if answer is not None and expected is not None else None
                ),
                "lexical_normalized_exact_match": (
                    normalized_answer == normalized_expected
                    if normalized_answer is not None and normalized_expected is not None
                    else None
                ),
                "lexical_keyword_coverage": keyword_coverage,
                "has_answer": bool(answer and answer.strip()),
                "has_citations": bool(target_result.citations),
            }
        )


def _keyword_coverage(
    *,
    normalized_answer: str | None,
    metadata: dict[str, object],
) -> float | None:
    raw_keywords = metadata.get("keywords")
    if (
        normalized_answer is None
        or not isinstance(raw_keywords, list)
        or not raw_keywords
        or any(not isinstance(keyword, str) for keyword in raw_keywords)
    ):
        return None
    keywords = tuple(
        _normalize_lexical_answer(keyword)
        for keyword in raw_keywords
        if isinstance(keyword, str) and keyword.strip()
    )
    if not keywords:
        return None
    matched = sum(
        1
        for keyword in keywords
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", normalized_answer)
    )
    return matched / len(keywords)
