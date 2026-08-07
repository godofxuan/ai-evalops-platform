import hashlib
import json
from pathlib import Path

import pytest

import scripts.run_load_test as run_load_test
from scripts.experiment_support import (
    ExperimentError,
    bind_dataset_version,
    failed_experiment_envelope,
    percentile,
    write_report,
)
from scripts.gate1_image_evidence import compute_docker_build_context_binding
from scripts.run_concurrency_test import build_parser as concurrency_parser
from scripts.run_failure_scenarios import build_parser as failure_parser
from scripts.run_load_test import build_parser as load_parser
from scripts.run_load_test import main as load_main
from scripts.worker_scaling_protocol import build_balanced_arm_plan


def _fake_local_image_binding(**kwargs: object) -> dict[str, object]:
    repository = Path(kwargs["repository"])
    source_commit = str(kwargs["source_commit"])
    dockerfile_path = Path(kwargs["dockerfile_path"])
    dockerignore_path = Path(kwargs["dockerignore_path"])
    dockerfile_sha256 = hashlib.sha256(dockerfile_path.read_bytes()).hexdigest()
    created = "2026-07-30T00:00:00Z"
    build_context = compute_docker_build_context_binding(
        repository=repository,
        dockerignore_path=dockerignore_path,
    )
    context_sha256 = str(build_context["sha256"])
    source = "https://github.com/godofxuan/ai-evalops-platform"
    return {
        "identity_kind": "LOCAL_IMAGE_ID",
        "verification": "LOCAL_IMAGE_ID_VERIFIED",
        "repository": "ai-evalops-platform",
        "tag": "phase9",
        "reference": "ai-evalops-platform:phase9",
        "immutable_id": f"sha256:{'a' * 64}",
        "registry_digest": None,
        "compose_project": "ai-evalops-platform",
        "source_commit": source_commit,
        "source": source,
        "dockerfile_sha256": dockerfile_sha256,
        "build_context": build_context,
        "build": {
            "created": created,
        },
        "runtime": {
            "python": "3.12.13",
            "os": "linux",
            "architecture": "amd64",
        },
        "labels": {
            "org.opencontainers.image.revision": source_commit,
            "org.opencontainers.image.source": source,
            "org.opencontainers.image.created": created,
            "io.ai-evalops.dockerfile.sha256": dockerfile_sha256,
            "io.ai-evalops.build-context.sha256": context_sha256,
            "io.ai-evalops.python.version": "3.12.13",
        },
    }


@pytest.fixture(autouse=True)
def _replace_external_gate1_image_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_load_test,
        "build_gate1_image_binding",
        _fake_local_image_binding,
    )


def test_experiment_percentile_uses_documented_linear_interpolation() -> None:
    values = [10.0, 20.0, 30.0, 40.0]

    assert percentile(values, 0.50) == 25.0
    assert percentile(values, 0.95) == 38.5
    assert percentile([], 0.95) is None


def test_dataset_version_binding_rejects_server_digest_mismatch() -> None:
    with pytest.raises(ExperimentError, match="server dataset digest"):
        bind_dataset_version(
            {"id": "version-1", "sha256": "b" * 64, "case_count": 500},
            expected_sha256="a" * 64,
            expected_case_count=500,
        )

    assert bind_dataset_version(
        {"id": "version-1", "sha256": "a" * 64, "case_count": 500},
        expected_sha256="a" * 64,
        expected_case_count=500,
    ) == {
        "id": "version-1",
        "sha256": "a" * 64,
        "case_count": 500,
    }


def test_result_writer_refuses_to_overwrite_prior_evidence(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    write_report(output, {"status": "completed"})

    with pytest.raises(ExperimentError, match="refusing to overwrite"):
        write_report(output, {"status": "replacement"})


def test_failed_experiment_record_contains_no_exception_message_or_secret() -> None:
    report = failed_experiment_envelope(
        experiment="fault",
        configuration={"cases": 1},
        error=RuntimeError("Bearer secret-must-not-be-recorded"),
    )

    assert report["status"] == "failed"
    assert report["error"] == {"type": "RuntimeError"}
    assert "secret-must-not-be-recorded" not in str(report)


def test_experiment_cli_defaults_cover_required_scale_and_concurrency() -> None:
    load = load_parser().parse_args([])
    concurrency = concurrency_parser().parse_args([])
    failure = failure_parser().parse_args([])

    assert load.workers == "1,2,4,8"
    assert load.cases == 500
    assert concurrency.requests == 20
    assert failure.allow_service_disruption is False
    assert failure.repetitions == 3
    assert failure.outage_seconds == 3
    assert failure.idempotency_concurrency == 20
    assert failure.source_commit == "UNSPECIFIED"


def test_worker_scaling_plan_balances_every_worker_count_across_positions() -> None:
    arms = build_balanced_arm_plan()

    assert len(arms) == 32
    assert len({arm.arm_id for arm in arms}) == 32
    for workload in {"io_latency_v1", "transient_5pct_v1"}:
        workload_arms = [arm for arm in arms if arm.workload == workload]
        assert {arm.repetition for arm in workload_arms} == {1, 2, 3, 4}
        for position in range(1, 5):
            assert {arm.workers for arm in workload_arms if arm.position == position} == {
                1,
                2,
                4,
                8,
            }


def test_load_prepare_mode_creates_run_scoped_manifest(tmp_path: Path) -> None:
    output_root = tmp_path / "load"

    exit_code = load_main(
        [
            "--prepare-only",
            "--output-root",
            str(output_root),
            "--run-id",
            "gate1-contract",
            "--seed",
            "1729",
        ]
    )

    manifest_path = output_root / "gate1-contract" / "manifest.json"
    assert exit_code == 0
    for evidence_directory in ("raw", "summary", "failures", "plots"):
        assert (manifest_path.parent / evidence_directory).is_dir()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    protocol_bytes = (manifest_path.parent / "protocol.md").read_bytes()
    compose_bytes = Path("deploy/compose.yaml").read_bytes()
    dockerfile_bytes = Path("Dockerfile").read_bytes()
    dockerignore_bytes = Path(".dockerignore").read_bytes()
    arm_plan_bytes = (manifest_path.parent / "arm_order.json").read_bytes()
    dataset_hashes_bytes = (manifest_path.parent / "dataset" / "hashes.json").read_bytes()
    assert {
        key: manifest[key]
        for key in (
            "schema_version",
            "experiment",
            "run_id",
            "status",
            "formal_run_started",
            "seed",
        )
    } == {
        "schema_version": 6,
        "experiment": "worker_scaling",
        "run_id": "gate1-contract",
        "status": "prepared",
        "formal_run_started": False,
        "seed": 1729,
    }
    assert manifest["protocol"] == {
        "path": "protocol.md",
        "sha256": hashlib.sha256(protocol_bytes).hexdigest(),
    }
    assert len(manifest["provenance"]["source_commit"]) == 40
    assert manifest["provenance"]["compose"] == {
        "path": "deploy/compose.yaml",
        "sha256": hashlib.sha256(compose_bytes).hexdigest(),
    }
    assert manifest["provenance"]["dockerfile"] == {
        "path": "Dockerfile",
        "sha256": hashlib.sha256(dockerfile_bytes).hexdigest(),
    }
    assert manifest["provenance"]["dockerignore"] == {
        "path": ".dockerignore",
        "sha256": hashlib.sha256(dockerignore_bytes).hexdigest(),
    }
    assert manifest["provenance"]["image"] == _fake_local_image_binding(
        repository=Path.cwd(),
        source_commit=manifest["provenance"]["source_commit"],
        dockerfile_path=Path.cwd() / "Dockerfile",
        dockerignore_path=Path.cwd() / ".dockerignore",
    )
    expected_scripts = {
        path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for path in (
            "scripts/experiment_support.py",
            "scripts/gate1_collectors.py",
            "scripts/gate1_database.py",
            "scripts/gate1_evidence.py",
            "scripts/gate1_finalization.py",
            "scripts/gate1_image_evidence.py",
            "scripts/gate1_plots.py",
            "scripts/gate1_preflight.py",
            "scripts/gate1_prepared_evidence.py",
            "scripts/run_load_test.py",
            "scripts/worker_scaling_protocol.py",
        )
    }
    assert manifest["provenance"]["execution_scripts"] == {
        "algorithm": "sha256",
        "files": expected_scripts,
    }
    configuration = manifest["configuration"]
    assert configuration["values"] == {
        "api_url": "http://127.0.0.1:8000",
        "api_key_env": "EVALOPS_EXPERIMENT_API_KEY",
        "database_url_env": "EVALOPS_EXPERIMENT_DATABASE_URL",
        "workers": [1, 2, 4, 8],
        "cases": 500,
        "warmup_cases": 50,
        "delay_ms": 25,
        "poll_seconds": 0.5,
        "deadline_seconds": 900.0,
        "readiness_deadline_seconds": 120,
        "collector_interval_seconds": 1.0,
        "seed": 1729,
        "repetitions": 4,
    }
    configuration_bytes = json.dumps(
        configuration["values"],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert configuration["sha256"] == hashlib.sha256(configuration_bytes).hexdigest()
    assert manifest["dataset"]["hashes_path"] == "dataset/hashes.json"
    assert manifest["dataset"]["hashes_sha256"] == hashlib.sha256(dataset_hashes_bytes).hexdigest()
    assert manifest["arm_plan"]["sha256"] == hashlib.sha256(arm_plan_bytes).hexdigest()
    assert manifest["result_schema_version"] == 4
    assert manifest["quality_gate"] == {
        "automatic_evaluation": True,
        "policy": "all_expected_arms_valid_for_capacity_comparison",
        "policy_version": 1,
        "non_waivable": True,
    }
    assert manifest["adoption_gate"] == {
        "automatic_worker_count_change": False,
        "automatic_adoption_decision": False,
        "decision_owner": "human",
        "performance_thresholds_owner": "human",
    }


def test_load_prepare_mode_rejects_run_id_path_traversal(tmp_path: Path) -> None:
    output_root = tmp_path / "load"
    escaped = tmp_path / "escaped"

    exit_code = load_main(
        [
            "--prepare-only",
            "--output-root",
            str(output_root),
            "--run-id",
            "../escaped",
        ]
    )

    assert exit_code == 1
    assert not escaped.exists()


def test_load_prepare_image_build_failure_leaves_no_partial_run_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "load"

    def fail_image_build(**kwargs: object) -> dict[str, object]:
        del kwargs
        raise ExperimentError("synthetic image build failure")

    monkeypatch.setattr(
        run_load_test,
        "build_gate1_image_binding",
        fail_image_build,
    )

    exit_code = load_main(
        [
            "--prepare-only",
            "--output-root",
            str(output_root),
            "--run-id",
            "gate1-image-failure",
        ]
    )

    assert exit_code == 1
    assert not (output_root / "gate1-image-failure").exists()


def test_load_execute_mode_preserves_preflight_failure_before_any_arm(
    tmp_path: Path,
    clean_gate1_repository: Path,
) -> None:
    assert clean_gate1_repository == Path.cwd()
    output_root = tmp_path / "load"
    common = [
        "--output-root",
        str(output_root),
        "--run-id",
        "gate1-preflight",
    ]

    assert load_main(["--prepare-only", *common]) == 0
    assert load_main(["--execute-prepared", *common]) == 1

    failure_path = output_root / "gate1-preflight" / "failures" / "preflight.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    assert failure["ready"] is False
    assert failure["status"] == "ENVIRONMENT_BLOCKED"
    assert "quality_gate_confirmed" in failure["blockers"]
    assert "adoption_gate_confirmed" in failure["blockers"]
    assert not any((output_root / "gate1-preflight" / "raw").iterdir())


def test_load_execute_mode_revalidates_bundle_before_environment_preflight(
    tmp_path: Path,
    clean_gate1_repository: Path,
) -> None:
    assert clean_gate1_repository == Path.cwd()
    output_root = tmp_path / "load"
    common = [
        "--output-root",
        str(output_root),
        "--run-id",
        "gate1-stale-evidence",
    ]
    run_directory = output_root / "gate1-stale-evidence"

    assert load_main(["--prepare-only", *common]) == 0
    measurement_path = run_directory / "dataset" / "measurement.jsonl"
    measurement_path.write_bytes(measurement_path.read_bytes() + b'{"tampered":true}\n')

    assert load_main(["--execute-prepared", *common]) == 1

    failure = json.loads(
        (run_directory / "failures" / "preflight.json").read_text(encoding="utf-8")
    )
    assert failure["status"] == "HASH_MISMATCH"
    assert failure["checks"]["measurement_hash_matches"] is False
    assert "runtime" not in failure
    assert not any((run_directory / "raw").iterdir())


def test_load_execute_mode_rejects_runtime_configuration_drift(
    tmp_path: Path,
    clean_gate1_repository: Path,
) -> None:
    assert clean_gate1_repository == Path.cwd()
    output_root = tmp_path / "load"
    common = [
        "--output-root",
        str(output_root),
        "--run-id",
        "gate1-config-drift",
    ]
    run_directory = output_root / "gate1-config-drift"

    assert load_main(["--prepare-only", *common]) == 0
    assert (
        load_main(
            [
                "--execute-prepared",
                *common,
                "--collector-interval-seconds",
                "60",
            ]
        )
        == 1
    )

    failure = json.loads(
        (run_directory / "failures" / "preflight.json").read_text(encoding="utf-8")
    )
    assert failure["status"] == "HASH_MISMATCH"
    assert failure["checks"]["requested_configuration_matches"] is False
    assert "requested_configuration_matches" in failure["blockers"]
    assert "runtime" not in failure


def test_load_prepare_mode_freezes_hashed_dual_workload_dataset(tmp_path: Path) -> None:
    output_root = tmp_path / "load"

    exit_code = load_main(
        [
            "--prepare-only",
            "--output-root",
            str(output_root),
            "--run-id",
            "gate1-dataset",
            "--cases",
            "500",
            "--delay-ms",
            "50",
        ]
    )

    dataset_root = output_root / "gate1-dataset" / "dataset"
    dataset_bytes = (dataset_root / "measurement.jsonl").read_bytes()
    warmup_bytes = (dataset_root / "warmup.jsonl").read_bytes()
    hashes = json.loads((dataset_root / "hashes.json").read_text(encoding="utf-8"))
    cases = [json.loads(line) for line in dataset_bytes.splitlines()]
    warmup_cases = [json.loads(line) for line in warmup_bytes.splitlines()]
    transient_case_ids = {
        case["case_id"]
        for case in cases
        if case["metadata"]["mock_profiles"]["transient_5pct_v1"]["fail_until_attempt"] == 1
    }
    expected_transient_ids = set(
        sorted(
            (f"load-{index:04d}" for index in range(500)),
            key=lambda case_id: hashlib.sha256(case_id.encode()).hexdigest(),
        )[:25]
    )

    assert exit_code == 0
    assert len(cases) == 500
    assert hashes == {
        "algorithm": "sha256",
        "measurement_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "measurement_bytes": len(dataset_bytes),
        "measurement_cases": 500,
        "warmup_sha256": hashlib.sha256(warmup_bytes).hexdigest(),
        "warmup_bytes": len(warmup_bytes),
        "warmup_cases": 50,
    }
    assert len(warmup_cases) == 50
    assert {case["case_id"] for case in cases}.isdisjoint(case["case_id"] for case in warmup_cases)
    assert transient_case_ids == expected_transient_ids
    assert {profile for case in cases for profile in case["metadata"]["mock_profiles"]} == {
        "io_latency_v1",
        "transient_5pct_v1",
    }


def test_load_prepare_mode_freezes_repeated_seeded_arm_order(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    common_arguments = [
        "--prepare-only",
        "--run-id",
        "gate1-order",
        "--workers",
        "1,2,4,8",
        "--repetitions",
        "3",
        "--seed",
        "1729",
    ]

    assert load_main([*common_arguments, "--output-root", str(first_root)]) == 0
    assert load_main([*common_arguments, "--output-root", str(second_root)]) == 0

    first_plan = json.loads(
        (first_root / "gate1-order" / "arm_order.json").read_text(encoding="utf-8")
    )
    second_plan = json.loads(
        (second_root / "gate1-order" / "arm_order.json").read_text(encoding="utf-8")
    )
    arms = first_plan["arms"]
    pair_counts = {
        (workload, workers): sum(
            arm["workload"] == workload and arm["workers"] == workers for arm in arms
        )
        for workload in ("io_latency_v1", "transient_5pct_v1")
        for workers in (1, 2, 4, 8)
    }

    assert first_plan == second_plan
    assert len(arms) == 24
    assert pair_counts == {
        (workload, workers): 3
        for workload in ("io_latency_v1", "transient_5pct_v1")
        for workers in (1, 2, 4, 8)
    }
    assert all(arm["warmup_required"] is True for arm in arms)
    assert all(
        len({arm["workers"] for arm in arms[index : index + 3]}) > 1
        for index in range(len(arms) - 2)
    )


def test_load_prepare_mode_defaults_to_four_position_balanced_repetitions(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "load"

    assert (
        load_main(
            [
                "--prepare-only",
                "--output-root",
                str(output_root),
                "--run-id",
                "gate1-balanced-default",
                "--seed",
                "1729",
            ]
        )
        == 0
    )

    plan = json.loads(
        (output_root / "gate1-balanced-default" / "arm_order.json").read_text(encoding="utf-8")
    )
    arms = plan["arms"]

    assert plan["algorithm"] == "position-balanced-v1"
    assert plan["repetitions"] == 4
    assert len(arms) == 32
    for workload in ("io_latency_v1", "transient_5pct_v1"):
        workload_arms = [arm for arm in arms if arm["workload"] == workload]
        for position in range(1, 5):
            assert {arm["workers"] for arm in workload_arms if arm["position"] == position} == {
                1,
                2,
                4,
                8,
            }
