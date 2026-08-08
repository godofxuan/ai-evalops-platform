import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.release_evidence import assess_release_bundle

CURRENT_SOURCE = "a" * 40
HISTORICAL_SOURCE = "b" * 40
ARM_ID = "fair-q1000-single-w1-b20"


def _row(*, source_commit: str = CURRENT_SOURCE) -> dict[str, object]:
    return {
        "arm_id": ARM_ID,
        "source_commit": source_commit,
        "submitted_count": 1_000,
        "unique_job_count": 1_000,
        "terminal_count": 1_000,
        "lost_count": 0,
        "duplicate_durable_result_count": 0,
        "stale_success_accepted_count": 0,
        "stale_failure_accepted_count": 0,
        "illegal_state_transition_count": 0,
        "orphan_nonterminal_count": 0,
    }


def _write_bundle(
    root: Path,
    *,
    rows: list[dict[str, object]] | None = None,
    source_commit: str = CURRENT_SOURCE,
    claim_scope: str = "current_release_capacity",
    include_explain: bool = True,
    empty_csv: bool = False,
) -> Path:
    root.mkdir()
    csv_path = root / "arms.csv"
    selected_rows = rows if rows is not None else [_row(source_commit=source_commit)]
    if empty_csv:
        csv_path.write_bytes(b"")
    else:
        with csv_path.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(selected_rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(selected_rows)
    if include_explain:
        explain_path = root / "explain" / "fair.json"
        explain_path.parent.mkdir()
        explain_path.write_text(
            json.dumps(
                {
                    "format": "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)",
                    "planning_time_ms": 1.0,
                    "execution_time_ms": 2.0,
                    "plan": [{"Plan": {"Node Type": "Limit", "Actual Rows": 20}}],
                },
                sort_keys=True,
            )
            + "\n",
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
                "schema_version": 1,
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
