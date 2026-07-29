from app.reviews.agreement import calculate_agreement


def test_agreement_and_cohen_kappa_use_reviewer_marginal_distributions() -> None:
    metrics = calculate_agreement([(1, 1), (1, 2), (2, 2), (2, 2)])

    assert metrics.paired_labels == 4
    assert metrics.exact_agreement == 0.75
    assert metrics.cohen_kappa == 0.5


def test_kappa_is_undefined_when_both_reviewers_use_only_one_category() -> None:
    metrics = calculate_agreement([(3, 3), (3, 3)])

    assert metrics.exact_agreement == 1.0
    assert metrics.cohen_kappa is None
