from __future__ import annotations

from app.product_experiments.report import render_experiment_html


def test_report_escapes_untrusted_case_content_and_explains_demo_boundary() -> None:
    result = {
        "schema_version": "evalops.experiment-result/1.0",
        "experiment_id": "demo",
        "status": "DEMO_PASS",
        "scope": "DEMO",
        "case_count": 1,
        "source_identities": {},
        "dataset_sha256": "d" * 64,
        "evalops_sha": "e" * 40,
        "human_review_status": "PENDING",
        "formal_quality_claim_allowed": False,
        "production_ready": False,
        "automated_assessment": {"status": "PASS", "metrics": {}},
        "case_comparisons": [
            {
                "case_id": "case-1",
                "category": "basic",
                "baseline_answer": "<script>alert(1)</script>",
                "candidate_answer": "safe",
                "baseline_task_success": 0.0,
                "candidate_task_success": 1.0,
                "task_success_delta": 0.0,
                "baseline_citation_correctness": 0.0,
                "candidate_citation_correctness": 1.0,
                "baseline_tool_error_rate": 0.0,
                "candidate_tool_error_rate": 0.0,
                "baseline_latency_ms": 10.0,
                "candidate_latency_ms": 11.0,
                "latency_delta_ms": 1.0,
                "baseline_cost_usd": 0.01,
                "candidate_cost_usd": 0.01,
                "cost_delta_usd": 0.0,
                "baseline_trace_id": "trace-b",
                "candidate_trace_id": "trace-c",
            }
        ],
        "input_requirements": [],
    }

    rendered = render_experiment_html(result)

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "演示通过不等于正式质量提升" in rendered
    assert "trace-b / trace-c" in rendered


def test_agent_report_escapes_tool_trace_and_renders_agent_metrics() -> None:
    rendered = render_experiment_html(
        {
            "experiment_id": "agent-demo",
            "task_type": "AGENT_TOOL_USE",
            "status": "DEMO_PASS",
            "scope": "DEMO",
            "case_count": 1,
            "case_comparisons": [
                {
                    "case_id": "agent-1",
                    "category": "authorization",
                    "baseline_answer": "done",
                    "candidate_answer": "done",
                    "baseline_task_success": 1,
                    "candidate_task_success": 1,
                    "baseline_citation_correctness": 1,
                    "candidate_citation_correctness": 1,
                    "baseline_tool_error_rate": 0,
                    "candidate_tool_error_rate": 0,
                    "baseline_latency_ms": 1,
                    "candidate_latency_ms": 1,
                    "baseline_cost_usd": 0,
                    "candidate_cost_usd": 0,
                    "baseline_trace_id": "b",
                    "candidate_trace_id": "c",
                    "baseline_tool_calls": [
                        {"name": "<script>", "arguments": {}, "status": "success"}
                    ],
                    "candidate_tool_calls": [],
                    "baseline_agent_metrics": {"policy_violation_rate": 1.0},
                    "candidate_agent_metrics": {"policy_violation_rate": 0.0},
                }
            ],
            "automated_assessment": {},
            "input_requirements": [],
        }
    )

    assert "Agent tool-use trace" in rendered
    assert "&lt;script&gt;" in rendered
    assert "policy_violation_rate" in rendered
    assert "<script>" not in rendered
