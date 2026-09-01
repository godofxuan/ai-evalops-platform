from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.project_scorecard import (
    ScorecardEvidenceError,
    build_scorecard,
    render_markdown,
    verify_scorecard,
)


def test_project_scorecard_recomputes_authoritative_evidence() -> None:
    scorecard = build_scorecard()

    assert scorecard["overall_decision"] == {
        "portfolio": "READY_WITH_EXPLICIT_LIMITS",
        "release": "NOT_READY_NEGATIVE_SCALING_AND_QUALITY_INPUT_BLOCKED",
        "production": "NOT_VERIFIED",
    }
    assert scorecard["source_evidence"]["final_pair_evalops_sha"] == (
        "4040fa1db7cee6c8380ff8580fa21be17464435b"
    )
    assert scorecard["source_evidence"]["scorecard_source_sha"] == (
        "0e66aed4d40ee33d3488605d536e6aaa4a299e78"
    )
    categories = scorecard["categories"]
    assert categories["engineering_correctness"]["status"] == "VERIFIED_CONTROLLED"
    assert categories["agent_rag_quality"]["status"] == "QUALITY_EVIDENCE_INSUFFICIENT"
    assert categories["performance_scalability"]["status"] == "NEGATIVE_SCALING"
    diagnostics = categories["performance_scalability"]["metrics"]["diagnostic_signals"]
    assert len(diagnostics) == 4
    assert diagnostics[0]["claim_latency_p95_multiplier"] > 4.0
    assert categories["performance_scalability"]["hypothesis_status"] == {
        "hot_row_contention": "ASSOCIATED_NOT_CAUSALLY_PROVEN",
        "postgres_lock_pressure": "ASSOCIATED_NOT_CAUSALLY_PROVEN",
        "worker_coordination_overhead": "UNRESOLVED",
        "measurement_perturbation": "NOT_RULED_OUT",
    }
    assert categories["reliability"]["metrics"]["protected_counters"] == {
        "lost_count": 0,
        "duplicate_durable_result_count": 0,
        "stale_success_accepted_count": 0,
        "stale_failure_accepted_count": 0,
        "illegal_state_transition_count": 0,
        "orphan_nonterminal_count": 0,
        "attempt_sequence_mismatch_count": 0,
    }
    assert (
        "mcp_audit_delivery_latency_seconds"
        in categories["reliability"]["metrics"]["operational_metric_catalog"]
    )
    assert scorecard["scoring_policy"]["weighted_total"] is None
    verify_scorecard(scorecard)


def test_project_scorecard_detects_manual_status_upgrade() -> None:
    scorecard = deepcopy(build_scorecard())
    scorecard["categories"]["agent_rag_quality"]["status"] = "PASS"

    with pytest.raises(ScorecardEvidenceError, match="differs from authoritative evidence"):
        verify_scorecard(scorecard)


def test_project_scorecard_markdown_preserves_release_boundary() -> None:
    markdown = render_markdown(build_scorecard())

    assert "no weighted total" in markdown
    assert "NOT_READY_NEGATIVE_SCALING_AND_QUALITY_INPUT_BLOCKED" in markdown
    assert "PRODUCTION: `NOT_VERIFIED`" in markdown.upper()
