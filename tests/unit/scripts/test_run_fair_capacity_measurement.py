import argparse

import pytest

from scripts.experiment_support import ExperimentError
from scripts.run_fair_capacity_test import _measurement_contract, build_parser


def _arguments(*extra: str) -> argparse.Namespace:
    return build_parser().parse_args(
        [
            "--run-id",
            "measurement-1",
            "--source-commit",
            "a" * 40,
            "--stage",
            "targeted",
            "--queue-sizes",
            "1000",
            "--sample-jobs",
            "100",
            "--arm-id",
            "fair-q1000-skew_20_to_1-w8-b1",
            *extra,
        ]
    )


def _complete_identity() -> tuple[str, ...]:
    return (
        "--measurement-mode",
        "ON",
        "--measurement-block",
        "A",
        "--measurement-order-position",
        "2",
        "--measurement-mode-repetition",
        "1",
        "--measurement-code-sha",
        "b" * 40,
        "--workflow-run-id",
        "123",
        "--postgres-telemetry-sampling-hz",
        "5",
    )


def test_measurement_runner_requires_complete_identity() -> None:
    args = _arguments("--measurement-mode", "ON")

    with pytest.raises(ExperimentError, match="identity must be complete"):
        _measurement_contract(args)


def test_measurement_runner_retires_synchronous_callback_observer() -> None:
    args = _arguments(*_complete_identity(), "--performance-attribution")

    with pytest.raises(ExperimentError, match="synchronous attribution observer is retired"):
        _measurement_contract(args)


def test_measurement_runner_freezes_representative_arm() -> None:
    args = _arguments(*_complete_identity())
    args.arm_id = "fair-q1000-single_tenant-w8-b1"

    with pytest.raises(ExperimentError, match="frozen representative arm"):
        _measurement_contract(args)


def test_measurement_runner_freezes_sample_jobs() -> None:
    args = _arguments(*_complete_identity())
    args.sample_jobs = 20

    with pytest.raises(ExperimentError, match="sample_jobs=100"):
        _measurement_contract(args)


def test_measurement_runner_accepts_passive_contract_without_production_changes() -> None:
    contract = _measurement_contract(_arguments(*_complete_identity()))

    assert contract == {
        "measurement_mode": "ON",
        "measurement_block": "A",
        "measurement_order_position": 2,
        "measurement_mode_repetition": 1,
        "measurement_code_sha": "b" * 40,
        "workflow_run_id": "123",
        "telemetry_sampling_hz": 5,
    }
