import hashlib

from app.product_experiments.report import render_experiment_html


def test_v3_report_front_screen_explains_failures_and_missing_comparability():
    rendered = render_experiment_html(
        {
            "schema_version": "evalops.experiment-result/3.0",
            "status": "EXECUTION_FAILED",
            "scope": "DEMO",
            "case_count": 20,
            "observations": {"baseline": {}, "candidate": {}},
            "execution_errors": [{"case_id": "bad", "error_code": "target_citation_invalid"}],
        }
    )
    for phrase in (
        "任务执行",
        "质量判定",
        "证据覆盖",
        "延迟与成本",
        "target_citation_invalid",
        "0 / 40",
        "semantic_support",
    ):
        assert phrase in rendered


def test_existing_v2_report_rendering_bytes_are_unchanged():
    rendered = render_experiment_html(
        {
            "schema_version": "evalops.experiment-result/2.0",
            "status": "EXECUTION_FAILED",
            "scope": "DEMO",
            "case_count": 20,
            "experiment_id": "legacy-control",
        }
    )
    assert hashlib.sha256(rendered.encode()).hexdigest() == (
        "437d008017b4f34049751e57571b417cd027de9efa05dd2a1a8f15f7b8f4f705"
    )
