from pathlib import Path

import pytest

from scripts.experiment_support import ExperimentError, percentile, write_report
from scripts.run_concurrency_test import build_parser as concurrency_parser
from scripts.run_failure_scenarios import build_parser as failure_parser
from scripts.run_load_test import build_parser as load_parser


def test_experiment_percentile_uses_documented_linear_interpolation() -> None:
    values = [10.0, 20.0, 30.0, 40.0]

    assert percentile(values, 0.50) == 25.0
    assert percentile(values, 0.95) == 38.5
    assert percentile([], 0.95) is None


def test_result_writer_refuses_to_overwrite_prior_evidence(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    write_report(output, {"status": "completed"})

    with pytest.raises(ExperimentError, match="refusing to overwrite"):
        write_report(output, {"status": "replacement"})


def test_experiment_cli_defaults_cover_required_scale_and_concurrency() -> None:
    load = load_parser().parse_args([])
    concurrency = concurrency_parser().parse_args([])
    failure = failure_parser().parse_args([])

    assert load.workers == "1,2,4,8"
    assert load.cases == 500
    assert concurrency.requests == 20
    assert failure.allow_service_disruption is False
    assert failure.lease_recovery_wait_seconds == 40
