import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.release_evidence import assess_release_bundle

CURRENT_SOURCE = "a" * 40
HISTORICAL_SOURCE = "b" * 40
ARM_ID = "fair-q1000-single_tenant-w1-b20"


def _row(*, source_commit: str = CURRENT_SOURCE) -> dict[str, object]:
    return {
        "arm_id": ARM_ID,
        "source_commit": source_commit,
        "queue_size": 1_000,
        "distribution": "single_tenant",
        "worker_concurrency": 1,
        "claim_batch_size": 20,
        "fair_first_secondary_tenant_position": "",
        "legacy_fifo_first_secondary_tenant_position": "",
        "submitted_count": 1_000,
        "unique_job_count": 1_000,
        "terminal_count": 1_000,
        "lost_count": 0,
        "duplicate_durable_result_count": 0,
        "stale_success_accepted_count": 0,
        "stale_failure_accepted_count": 0,
        "illegal_state_transition_count": 0,
        "orphan_nonterminal_count": 0,
        "attempt_sequence_mismatch_count": 0,
        "empty_while_eligible": 0,
    }


def _fair_plan(candidate_cardinality: int) -> list[dict[str, object]]:
    """Representative current fair selector shape from the preserved PostgreSQL evidence."""

    return [
        {
            "Plan": {
                "Node Type": "WindowAgg",
                "Actual Rows": candidate_cardinality,
                "Actual Loops": 1,
                "Plans": [
                    {
                        "Node Type": "Aggregate",
                        "Actual Rows": candidate_cardinality,
                        "Actual Loops": 1,
                        "Plans": [
                            {
                                "Node Type": "Bitmap Heap Scan",
                                "Relation Name": "evaluation_jobs",
                                "Actual Rows": 1_000,
                                "Actual Loops": 1,
                            }
                        ],
                    }
                ],
            },
            "Planning Time": 1.0,
            "Execution Time": 2.0,
        }
    ]


def _legacy_plan(candidate_cardinality: int) -> list[dict[str, object]]:
    """Representative current legacy selector shape where Limit hides the candidate set."""

    return [
        {
            "Plan": {
                "Node Type": "Limit",
                "Actual Rows": 20,
                "Actual Loops": 1,
                "Plans": [
                    {
                        "Node Type": "LockRows",
                        "Actual Rows": 20,
                        "Actual Loops": 1,
                        "Plans": [
                            {
                                "Node Type": "Sort",
                                "Actual Rows": 20,
                                "Actual Loops": 1,
                                "Plans": [
                                    {
                                        "Node Type": "Bitmap Heap Scan",
                                        "Relation Name": "evaluation_jobs",
                                        "Actual Rows": candidate_cardinality,
                                        "Actual Loops": 1,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            "Planning Time": 1.0,
            "Execution Time": 2.0,
        }
    ]


def _write_bundle(
    root: Path,
    *,
    rows: list[dict[str, object]] | None = None,
    source_commit: str = CURRENT_SOURCE,
    claim_scope: str = "current_release_capacity",
    include_explain: bool = True,
    explain_repetitions: int = 1,
    candidate_cardinality: int = 1_000,
    fair_candidate_cardinality: int | None = None,
    legacy_candidate_cardinality: int | None = None,
    schema_version: int = 1,
    tenant_count: int | None = None,
    candidate_units: dict[str, str] | None = None,
    raw_plans: dict[str, object] | None = None,
    empty_csv: bool = False,
) -> Path:
    root.mkdir()
    csv_path = root / "arms.csv"
    selected_rows = [
        dict(row) for row in (rows if rows is not None else [_row(source_commit=source_commit)])
    ]
    if tenant_count is not None:
        for row in selected_rows:
            row["tenant_count"] = tenant_count
    if empty_csv:
        csv_path.write_bytes(b"")
    else:
        with csv_path.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(selected_rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(selected_rows)
    if include_explain:
        for selector in ("fair", "legacy_fifo"):
            for repetition in range(1, explain_repetitions + 1):
                explain_path = root / "explain" / f"{selector}-r{repetition}.json"
                explain_path.parent.mkdir(exist_ok=True)
                selector_cardinality = (
                    fair_candidate_cardinality
                    if selector == "fair" and fair_candidate_cardinality is not None
                    else legacy_candidate_cardinality
                    if selector == "legacy_fifo" and legacy_candidate_cardinality is not None
                    else candidate_cardinality
                )
                explain_record: dict[str, object] = {
                    "format": "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)",
                    "arm_id": str(selected_rows[0].get("arm_id", ARM_ID)),
                    "selector": selector,
                    "repetition": repetition,
                    "planning_time_ms": 1.0,
                    "execution_time_ms": 2.0,
                    "candidate_cardinality": selector_cardinality,
                    "plan": (
                        raw_plans[selector]
                        if raw_plans is not None and selector in raw_plans
                        else _fair_plan(selector_cardinality)
                        if selector == "fair"
                        else _legacy_plan(selector_cardinality)
                    ),
                }
                if candidate_units is not None and selector in candidate_units:
                    explain_record["candidate_unit"] = candidate_units[selector]
                explain_path.write_text(
                    json.dumps(explain_record, sort_keys=True) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
    files: dict[str, dict[str, object]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        files[relative] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "status": "complete",
                "source_commit": source_commit,
                "claim_scope": claim_scope,
                "files": files,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return root


def _assess(root: Path, *, expected_arm_ids: tuple[str, ...] = (ARM_ID,)) -> dict[str, Any]:
    return assess_release_bundle(
        root,
        expected_source_commit=CURRENT_SOURCE,
        expected_arm_ids=expected_arm_ids,
    )


def test_release_bundle_requires_exact_source_sha(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "bundle", source_commit="not-an-exact-sha")

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "invalid_source_commit" in result["blockers"]


def test_release_bundle_fails_when_any_expected_arm_is_missing(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "bundle")

    result = _assess(bundle, expected_arm_ids=(ARM_ID, "fair-q10000-single-w1-b20"))

    assert result["status"] == "FAILED"
    assert result["missing_arm_ids"] == ["fair-q10000-single-w1-b20"]


def test_release_bundle_fails_on_duplicate_arm(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "bundle", rows=[_row(), _row()])

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert result["duplicate_arm_ids"] == [ARM_ID]


def test_release_bundle_cannot_verify_without_raw_postgresql_explain(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "bundle", include_explain=False)

    result = _assess(bundle)

    assert result["status"] in {"UNKNOWN", "FAILED"}
    assert "postgres_explain_missing" in result["blockers"]


def test_release_bundle_rejects_explain_candidate_cardinality_drift(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "bundle", candidate_cardinality=1)

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "postgres_explain_candidate_cardinality_mismatch" in result["blockers"]


def test_schema_v2_accepts_selector_specific_candidate_units(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "bundle",
        schema_version=2,
        tenant_count=1,
        fair_candidate_cardinality=1,
        legacy_candidate_cardinality=1_000,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
    )

    result = _assess(bundle)

    assert result["schema_version"] == 2
    assert result["status"] == "VERIFIED"
    assert result["blockers"] == []


def test_schema_v2_rejects_top_level_cardinality_when_raw_plan_disagrees(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(
        tmp_path / "bundle",
        schema_version=2,
        tenant_count=1,
        fair_candidate_cardinality=1,
        legacy_candidate_cardinality=1_000,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
        raw_plans={
            "fair": _fair_plan(20),
            "legacy_fifo": _legacy_plan(1_000),
        },
    )

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "postgres_explain_raw_plan_cardinality_mismatch" in result["blockers"]


def test_schema_v2_rejects_tampered_raw_plan_with_recomputed_manifest(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "bundle",
        schema_version=2,
        tenant_count=1,
        fair_candidate_cardinality=1,
        legacy_candidate_cardinality=1_000,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
        raw_plans={
            "fair": _fair_plan(20),
            "legacy_fifo": _legacy_plan(1_000),
        },
    )

    result = _assess(bundle)

    assert "manifest_hash_mismatch" not in result["blockers"]
    assert "postgres_explain_raw_plan_cardinality_mismatch" in result["blockers"]


def test_schema_v2_accepts_real_shaped_fair_explain(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "bundle",
        schema_version=2,
        tenant_count=1,
        fair_candidate_cardinality=1,
        legacy_candidate_cardinality=1_000,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
        raw_plans={"fair": _fair_plan(1), "legacy_fifo": _legacy_plan(1_000)},
    )

    assert _assess(bundle)["status"] == "VERIFIED"


def test_schema_v2_accepts_real_shaped_legacy_explain(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "bundle",
        schema_version=2,
        tenant_count=1,
        fair_candidate_cardinality=1,
        legacy_candidate_cardinality=1_000,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
        raw_plans={"fair": _fair_plan(1), "legacy_fifo": _legacy_plan(1_000)},
    )

    assert _assess(bundle)["status"] == "VERIFIED"


def test_schema_v2_rejects_missing_raw_plan_candidate_node(tmp_path: Path) -> None:
    bundle = _write_bundle(
        tmp_path / "bundle",
        schema_version=2,
        tenant_count=1,
        fair_candidate_cardinality=1,
        legacy_candidate_cardinality=1_000,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
        raw_plans={
            "fair": [{"Plan": {"Node Type": "Limit", "Actual Rows": 1, "Actual Loops": 1}}],
            "legacy_fifo": _legacy_plan(1_000),
        },
    )

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "postgres_explain_raw_plan_candidate_missing" in result["blockers"]


def test_schema_v2_rejects_ambiguous_raw_plan_cardinality(tmp_path: Path) -> None:
    ambiguous_fair_plan = _fair_plan(1)
    root = ambiguous_fair_plan[0]["Plan"]
    assert isinstance(root, dict)
    root["Plans"].append({"Node Type": "WindowAgg", "Actual Rows": 1, "Actual Loops": 1})
    bundle = _write_bundle(
        tmp_path / "bundle",
        schema_version=2,
        tenant_count=1,
        fair_candidate_cardinality=1,
        legacy_candidate_cardinality=1_000,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
        raw_plans={"fair": ambiguous_fair_plan, "legacy_fifo": _legacy_plan(1_000)},
    )

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "postgres_explain_raw_plan_candidate_ambiguous" in result["blockers"]


@pytest.mark.parametrize(
    ("distribution", "tenant_count"),
    [
        ("single_tenant", 1),
        ("balanced_multi_tenant", 4),
        ("skew_20_to_1", 2),
        ("many_small_tenants", 100),
    ],
)
def test_schema_v2_accepts_frozen_tenant_count_for_every_distribution(
    tmp_path: Path,
    distribution: str,
    tenant_count: int,
) -> None:
    row = _row()
    arm_id = f"fair-q1000-{distribution}-w1-b20"
    row["arm_id"] = arm_id
    row["distribution"] = distribution
    if distribution == "skew_20_to_1":
        row["fair_first_secondary_tenant_position"] = 2
        row["legacy_fifo_first_secondary_tenant_position"] = 3
    bundle = _write_bundle(
        tmp_path / "bundle",
        rows=[row],
        schema_version=2,
        tenant_count=tenant_count,
        fair_candidate_cardinality=tenant_count,
        legacy_candidate_cardinality=1_000,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
    )

    result = _assess(bundle, expected_arm_ids=(arm_id,))

    assert result["status"] == "VERIFIED"
    assert result["blockers"] == []


@pytest.mark.parametrize(
    ("fair_cardinality", "legacy_cardinality"),
    [(2, 1_000), (1, 999)],
)
def test_schema_v2_rejects_selector_specific_cardinality_drift(
    tmp_path: Path,
    fair_cardinality: int,
    legacy_cardinality: int,
) -> None:
    bundle = _write_bundle(
        tmp_path / "bundle",
        schema_version=2,
        tenant_count=1,
        fair_candidate_cardinality=fair_cardinality,
        legacy_candidate_cardinality=legacy_cardinality,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
    )

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "postgres_explain_candidate_cardinality_mismatch" in result["blockers"]


@pytest.mark.parametrize(
    "candidate_units",
    [
        {"legacy_fifo": "eligible_jobs"},
        {"fair": "eligible_jobs", "legacy_fifo": "eligible_jobs"},
        {
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_tenant_round_members",
        },
    ],
)
def test_schema_v2_rejects_missing_or_wrong_candidate_unit(
    tmp_path: Path,
    candidate_units: dict[str, str],
) -> None:
    bundle = _write_bundle(
        tmp_path / "bundle",
        schema_version=2,
        tenant_count=1,
        fair_candidate_cardinality=1,
        legacy_candidate_cardinality=1_000,
        candidate_units=candidate_units,
    )

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "postgres_explain_candidate_unit_mismatch" in result["blockers"]


@pytest.mark.parametrize("tenant_count", [0, 2, 1_001])
def test_schema_v2_rejects_invalid_single_tenant_count(
    tmp_path: Path,
    tenant_count: int,
) -> None:
    bundle = _write_bundle(
        tmp_path / "bundle",
        schema_version=2,
        tenant_count=tenant_count,
        fair_candidate_cardinality=tenant_count,
        legacy_candidate_cardinality=1_000,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
    )

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "arms_tenant_count_invalid" in result["blockers"]


@pytest.mark.parametrize(
    ("field", "value", "tenant_count", "fair_cardinality", "legacy_cardinality"),
    [
        ("queue_size", 999, 1, 1, 999),
        ("distribution", "balanced_multi_tenant", 4, 4, 1_000),
        ("worker_concurrency", 8, 1, 1, 1_000),
        ("claim_batch_size", 1, 1, 1, 1_000),
    ],
)
def test_schema_v2_rejects_arm_metadata_spoofing(
    tmp_path: Path,
    field: str,
    value: object,
    tenant_count: int,
    fair_cardinality: int,
    legacy_cardinality: int,
) -> None:
    row = _row()
    row[field] = value
    bundle = _write_bundle(
        tmp_path / "bundle",
        rows=[row],
        schema_version=2,
        tenant_count=tenant_count,
        fair_candidate_cardinality=fair_cardinality,
        legacy_candidate_cardinality=legacy_cardinality,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
    )

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "arm_metadata_mismatch" in result["blockers"]


def test_schema_v2_rejects_nonzero_empty_while_eligible(tmp_path: Path) -> None:
    row = _row()
    row["empty_while_eligible"] = 1
    bundle = _write_bundle(
        tmp_path / "bundle",
        rows=[row],
        schema_version=2,
        tenant_count=1,
        fair_candidate_cardinality=1,
        legacy_candidate_cardinality=1_000,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
    )

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "empty_while_eligible_nonzero" in result["blockers"]


def test_schema_v2_rejects_missing_empty_while_eligible(tmp_path: Path) -> None:
    row = _row()
    del row["empty_while_eligible"]
    bundle = _write_bundle(
        tmp_path / "bundle",
        rows=[row],
        schema_version=2,
        tenant_count=1,
        fair_candidate_cardinality=1,
        legacy_candidate_cardinality=1_000,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
    )

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "empty_while_eligible_invalid" in result["blockers"]


def test_schema_v2_rejects_boolean_empty_while_eligible(tmp_path: Path) -> None:
    row = _row()
    row["empty_while_eligible"] = True
    bundle = _write_bundle(
        tmp_path / "bundle",
        rows=[row],
        schema_version=2,
        tenant_count=1,
        fair_candidate_cardinality=1,
        legacy_candidate_cardinality=1_000,
        candidate_units={
            "fair": "eligible_tenant_round_members",
            "legacy_fifo": "eligible_jobs",
        },
    )

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "empty_while_eligible_invalid" in result["blockers"]


def test_schema_v1_retains_historical_empty_semantics(tmp_path: Path) -> None:
    row = _row()
    del row["empty_while_eligible"]
    bundle = _write_bundle(tmp_path / "bundle", rows=[row], schema_version=1)

    result = _assess(bundle)

    assert result["status"] == "VERIFIED"
    assert "empty_while_eligible_invalid" not in result["blockers"]
    assert "empty_while_eligible_nonzero" not in result["blockers"]


def test_schema_v1_historical_failed_bundle_remains_failed() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    bundle = repository_root / "docs/results/release/v0.1.0/targeted-gh-31327388006-1/rep1/bundle"
    with (bundle / "arms.csv").open(encoding="utf-8", newline="") as stream:
        arm_ids = tuple(str(row["arm_id"]) for row in csv.DictReader(stream))

    result = assess_release_bundle(
        bundle,
        expected_source_commit="02f5e680e71d05c76c145da6895122a2cf04ba14",
        expected_arm_ids=arm_ids,
        expected_explain_repetitions=4,
    )

    assert result["schema_version"] == 1
    assert result["status"] == "FAILED"
    assert "postgres_explain_candidate_cardinality_mismatch" in result["blockers"]
    assert "empty_while_eligible_invalid" not in result["blockers"]
    assert "empty_while_eligible_nonzero" not in result["blockers"]


def test_release_bundle_requires_every_fair_and_legacy_explain_repetition(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path / "bundle")

    result = assess_release_bundle(
        bundle,
        expected_source_commit=CURRENT_SOURCE,
        expected_arm_ids=(ARM_ID,),
        expected_explain_repetitions=4,
    )

    assert result["status"] == "FAILED"
    assert "postgres_explain_coverage_mismatch" in result["blockers"]


def test_release_bundle_accepts_complete_fair_and_legacy_explain_coverage(
    tmp_path: Path,
) -> None:
    bundle = _write_bundle(tmp_path / "bundle", explain_repetitions=4)

    result = assess_release_bundle(
        bundle,
        expected_source_commit=CURRENT_SOURCE,
        expected_arm_ids=(ARM_ID,),
        expected_explain_repetitions=4,
    )

    assert result["status"] == "VERIFIED"
    assert "postgres_explain_coverage_mismatch" not in result["blockers"]


def test_release_bundle_does_not_treat_empty_csv_as_zero_failures(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "bundle", empty_csv=True)

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "arms_csv_empty" in result["blockers"]


def test_release_bundle_fails_when_submitted_differs_from_unique(tmp_path: Path) -> None:
    row = _row()
    row["unique_job_count"] = 999
    bundle = _write_bundle(tmp_path / "bundle", rows=[row])

    result = _assess(bundle)

    assert "submitted_unique_mismatch" in result["blockers"]


def test_release_bundle_fails_when_unique_differs_from_terminal(tmp_path: Path) -> None:
    row = _row()
    row["terminal_count"] = 999
    bundle = _write_bundle(tmp_path / "bundle", rows=[row])

    result = _assess(bundle)

    assert "unique_terminal_mismatch" in result["blockers"]


def test_release_bundle_fails_when_jobs_are_lost(tmp_path: Path) -> None:
    row = _row()
    row["lost_count"] = 1
    bundle = _write_bundle(tmp_path / "bundle", rows=[row])

    result = _assess(bundle)

    assert "lost_jobs" in result["blockers"]


def test_release_bundle_fails_on_duplicate_durable_result(tmp_path: Path) -> None:
    row = _row()
    row["duplicate_durable_result_count"] = 1
    bundle = _write_bundle(tmp_path / "bundle", rows=[row])

    result = _assess(bundle)

    assert "duplicate_durable_results" in result["blockers"]


def test_release_bundle_fails_when_stale_success_is_accepted(tmp_path: Path) -> None:
    row = _row()
    row["stale_success_accepted_count"] = 1
    bundle = _write_bundle(tmp_path / "bundle", rows=[row])

    result = _assess(bundle)

    assert "stale_success_accepted" in result["blockers"]


def test_release_bundle_fails_when_stale_failure_is_accepted(tmp_path: Path) -> None:
    row = _row()
    row["stale_failure_accepted_count"] = 1
    bundle = _write_bundle(tmp_path / "bundle", rows=[row])

    result = _assess(bundle)

    assert "stale_failure_accepted" in result["blockers"]


def test_release_bundle_fails_on_illegal_state_transition(tmp_path: Path) -> None:
    row = _row()
    row["illegal_state_transition_count"] = 1
    bundle = _write_bundle(tmp_path / "bundle", rows=[row])

    result = _assess(bundle)

    assert "illegal_state_transition" in result["blockers"]


def test_release_bundle_fails_on_attempt_sequence_mismatch(tmp_path: Path) -> None:
    row = _row()
    row["attempt_sequence_mismatch_count"] = 1
    bundle = _write_bundle(tmp_path / "bundle", rows=[row])

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "attempt_sequence_mismatch" in result["blockers"]


def test_release_bundle_fails_when_skew_secondary_tenant_appears_after_two(
    tmp_path: Path,
) -> None:
    row = _row()
    row["distribution"] = "skew_20_to_1"
    row["fair_first_secondary_tenant_position"] = 3
    row["legacy_fifo_first_secondary_tenant_position"] = 21
    bundle = _write_bundle(tmp_path / "bundle", rows=[row])

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "skew_fairness_regression" in result["blockers"]


@pytest.mark.parametrize("mutation", ["hash", "file_set"])
def test_release_bundle_fails_on_manifest_hash_or_file_set_mismatch(
    tmp_path: Path,
    mutation: str,
) -> None:
    bundle = _write_bundle(tmp_path / "bundle")
    if mutation == "hash":
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        manifest["files"]["arms.csv"]["sha256"] = "0" * 64
        (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    else:
        (bundle / "unmanifested.txt").write_text("drift\n", encoding="utf-8")

    result = _assess(bundle)

    expected = "manifest_hash_mismatch" if mutation == "hash" else "manifest_file_set_mismatch"
    assert result["status"] == "FAILED"
    assert expected in result["blockers"]


def test_release_bundle_rejects_non_sha256_manifest_digest(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "bundle")
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["arms.csv"]["sha256"] = "0" * 40
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "manifest_invalid" in result["blockers"]


def test_release_bundle_rejects_boolean_schema_version(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "bundle", schema_version=True)

    result = _assess(bundle)

    assert result["status"] == "FAILED"
    assert "manifest_invalid" in result["blockers"]


def test_old_source_cannot_be_presented_as_current_release_capacity(tmp_path: Path) -> None:
    current_claim = _write_bundle(
        tmp_path / "current-claim",
        rows=[_row(source_commit=HISTORICAL_SOURCE)],
        source_commit=HISTORICAL_SOURCE,
    )
    historical_claim = _write_bundle(
        tmp_path / "historical-claim",
        rows=[_row(source_commit=HISTORICAL_SOURCE)],
        source_commit=HISTORICAL_SOURCE,
        claim_scope="historical_baseline",
    )

    current_result = _assess(current_claim)
    historical_result = _assess(historical_claim)

    assert current_result["status"] == "FAILED"
    assert "historical_source_misclassified" in current_result["blockers"]
    assert historical_result["status"] == "VERIFIED"
    assert historical_result["claim_scope"] == "historical_baseline"


def test_complete_source_bound_release_bundle_is_verified(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "bundle")

    result = _assess(bundle)

    assert result["status"] == "VERIFIED"
    assert result["blockers"] == []
