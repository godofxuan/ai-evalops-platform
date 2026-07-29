from uuid import UUID

from app.domain.enums import JobStatus
from app.results.comparison import ComparableCase, ComparableRun, compare_runs

LEFT_VERSION = UUID("00000000-0000-0000-0000-000000000401")
RIGHT_VERSION = UUID("00000000-0000-0000-0000-000000000402")


def test_different_dataset_versions_warn_and_compare_only_case_intersection() -> None:
    comparison = compare_runs(
        ComparableRun(
            dataset_version_id=LEFT_VERSION,
            cases={
                "shared-failure": ComparableCase(JobStatus.FAILED, None, {}),
                "changed": ComparableCase(JobStatus.SUCCEEDED, 100, {"score": 0.4}),
                "left-only": ComparableCase(JobStatus.SUCCEEDED, 80, {"score": 1.0}),
            },
        ),
        ComparableRun(
            dataset_version_id=RIGHT_VERSION,
            cases={
                "shared-failure": ComparableCase(JobStatus.SUCCEEDED, 90, {"score": 0.8}),
                "changed": ComparableCase(JobStatus.SUCCEEDED, 70, {"score": 0.7}),
                "right-only": ComparableCase(JobStatus.FAILED, None, {}),
            },
        ),
    )

    assert comparison.warning == "dataset_versions_differ"
    assert comparison.intersection_count == 2
    assert comparison.left_only_count == 1
    assert comparison.right_only_count == 1
    assert comparison.only_left_failed == ("shared-failure",)
    assert comparison.only_right_failed == ()
    assert comparison.changed_cases[0].case_id == "changed"
    assert comparison.changed_cases[0].metric_deltas == {"score": 0.3}
    assert comparison.changed_cases[0].latency_delta_ms == -30
