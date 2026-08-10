from pathlib import Path

WORKFLOW = Path(".github/workflows/measurement-system-v2.yml")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_measurement_workflow_has_exact_counterbalanced_order() -> None:
    text = _workflow_text()
    calls = [
        "run_repetition 1 A OFF 1",
        "run_repetition 2 A ON 1",
        "run_repetition 3 A ON 2",
        "run_repetition 4 A OFF 2",
        "run_repetition 5 B ON 3",
        "run_repetition 6 B OFF 3",
        "run_repetition 7 B OFF 4",
        "run_repetition 8 B ON 4",
    ]

    assert all(text.count(call) == 1 for call in calls)
    assert [text.index(call) for call in calls] == sorted(text.index(call) for call in calls)


def test_measurement_workflow_never_runs_formal_attribution_or_sync_observer() -> None:
    text = _workflow_text()

    assert "--performance-attribution" not in text
    assert "Execute four formal" not in text
    assert "assess_performance_attribution" not in text


def test_measurement_workflow_separates_read_and_write_permissions() -> None:
    text = _workflow_text()
    measurement = text[text.index("  measurement:") : text.index("  preservation:")]
    preservation = text[text.index("  preservation:") :]

    assert "contents: read" in measurement
    assert "contents: write" not in measurement
    assert "contents: write" in preservation


def test_measurement_workflow_is_race_safe_and_never_force_pushes() -> None:
    text = _workflow_text()

    assert "cancel-in-progress: false" in text
    assert 'remote_tip="$(git rev-parse origin/codex/evidence-gate-1)"' in text
    assert '"$remote_tip" != "$GITHUB_SHA"' in text
    assert "PRESERVATION_CONFLICT" in text
    assert "--force" not in text
    assert "git rebase" not in text
    assert "git merge --" not in text


def test_measurement_workflow_locks_behavior_and_historical_evidence() -> None:
    text = _workflow_text()

    assert "0915c10d9176191f4f306590f029ed66809cf161" in text
    assert "1c87fb218e334790812080701bd74b81488bf19c" in text
    assert "2180646802d41abfb5b9fdb6abd7b203cbced1fb" in text
    assert "python -m scripts.behavioral_source_lock" in text
    assert "234347cce8872b75595b2cf312baaf25b74091ce" in text
    assert "e321f63661645f728481ef11587f94fec9a0547a" in text
    assert "e2eecf765fba7300ecd8d48f0e301c78c5cbcf96" in text
    assert "adab7f560790f840f9db60eb4fbc23e62201e81b" in text
