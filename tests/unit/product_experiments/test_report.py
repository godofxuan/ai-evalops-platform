from __future__ import annotations

from app.product_experiments.report import render_experiment_html


def test_report_escapes_untrusted_case_content_and_explains_demo_boundary() -> None:
    result = {
        "schema_version": "evalops.experiment-result/1.0",
        "experiment_id": "demo",
        "status": "DEMO_PASS",
        "scope": "DEMO",
        "case_count": 1,
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
                "task_success_delta": 0.0,
                "latency_delta_ms": 1.0,
                "cost_delta_usd": 0.0,
            }
        ],
        "input_requirements": [],
    }

    rendered = render_experiment_html(result)

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "演示通过不等于正式质量提升" in rendered
