from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgreementMetrics:
    paired_labels: int
    exact_agreement: float | None
    cohen_kappa: float | None


def calculate_agreement(
    pairs: Sequence[tuple[Hashable, Hashable]],
) -> AgreementMetrics:
    if not pairs:
        return AgreementMetrics(
            paired_labels=0,
            exact_agreement=None,
            cohen_kappa=None,
        )
    total = len(pairs)
    observed = sum(left == right for left, right in pairs) / total
    left_counts = Counter(left for left, _right in pairs)
    right_counts = Counter(right for _left, right in pairs)
    categories = set(left_counts) | set(right_counts)
    expected = sum(
        (left_counts[category] / total) * (right_counts[category] / total)
        for category in categories
    )
    kappa = None if expected == 1.0 else (observed - expected) / (1.0 - expected)
    return AgreementMetrics(
        paired_labels=total,
        exact_agreement=observed,
        cohen_kappa=kappa,
    )
