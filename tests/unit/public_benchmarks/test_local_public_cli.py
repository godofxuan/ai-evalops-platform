from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from app.public_benchmarks.local_pilot import encoded, read_json
from scripts.run_local_public_benchmarks import prepare_plan


def test_plan_keeps_gold_out_of_ollama_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    rows = [
        {
            "id": "public-1",
            "category": "simple_python",
            "ground_truth": "GOLD_MUST_NEVER_BE_SENT",
            "messages": [{"role": "user", "content": "Question without its answer"}],
        }
    ]
    raw = encoded(rows)
    manifest = {"cases_sha256": hashlib.sha256(raw).hexdigest()}
    (source / "cases.json").write_bytes(raw)
    (source / "manifest.json").write_bytes(encoded(manifest))
    monkeypatch.setattr("app.public_benchmarks.bfcl.prepare_pilot", lambda root: manifest)
    monkeypatch.setattr("scripts.run_local_public_benchmarks._sha", lambda: "b" * 40)
    monkeypatch.setattr(
        "scripts.run_local_public_benchmarks.inventory",
        lambda client: {
            "ollama_version": "TEST_FIXTURE",
            "models": [{"name": "qwen2.5:3b", "digest": "a" * 64}],
        },
    )
    plan = read_json(
        prepare_plan(source, tmp_path / "plan", benchmark="bfcl", models=("qwen2.5:3b",))
    )
    request = plan["requests"][0]
    assert "GOLD_MUST_NEVER_BE_SENT" not in encoded(request["request"]).decode()
    assert request["reference"]["ground_truth"] == "GOLD_MUST_NEVER_BE_SENT"
    assert plan["metadata"]["model_output_retries"] == 0


def test_gemma_plan_uses_real_pinned_cases_and_keeps_existing_default_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from scripts.run_local_public_benchmarks import MODELS

    source = Path(__file__).resolve().parents[3] / "artifacts/public-benchmark-20260912/bfcl"
    if not (source / "cases.json").is_file():
        pytest.skip("Requires the pinned public BFCL source, not a mocked source checker")
    original_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "TEST_FIXTURE"})
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={"models": [{"name": "gemma4:e2b-it-qat", "digest": "c" * 64}]},
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    frozen = read_json(
        prepare_plan(
            source, tmp_path / "gemma-plan", benchmark="bfcl", models=("gemma4:e2b-it-qat",)
        )
    )
    assert len(frozen["requests"]) == 100
    assert all(row["request"]["think"] is False for row in frozen["requests"])
    assert frozen["metadata"]["model_order"] == ["gemma4:e2b-it-qat"]
    assert MODELS == ("qwen2.5:3b", "qwen3.5:4b", "qwen3:8b")
    originals = {row["id"]: row for row in read_json(source / "cases.json")}
    for row in frozen["requests"]:
        assert row["request"]["messages"] == originals[row["case_id"]]["messages"]
        assert row["reference"] == originals[row["case_id"]]


def test_bad_bfcl_source_is_rejected_before_model_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "cases.json").write_bytes(encoded([]))
    (source / "manifest.json").write_bytes(encoded({"cases_sha256": "0" * 64}))
    monkeypatch.setattr("app.public_benchmarks.bfcl.prepare_pilot", lambda root: {})

    def no_network(client: Any) -> None:
        pytest.fail("Invalid source must not contact Ollama")

    monkeypatch.setattr("scripts.run_local_public_benchmarks.inventory", no_network)
    with pytest.raises(ValueError, match="bfcl_dataset_hash_mismatch"):
        prepare_plan(source, tmp_path / "plan", benchmark="bfcl")


def test_ragbench_reference_reconstruction_is_required_before_model_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "cases.json").write_bytes(encoded([]))
    (source / "manifest.json").write_bytes(encoded({}))

    def reject_source(path: Path) -> None:
        raise ValueError("Source revision mismatch")

    monkeypatch.setattr("scripts.prepare_ragbench_pilot.load_source_cache", reject_source)
    with pytest.raises(ValueError, match="Source revision mismatch"):
        prepare_plan(source, tmp_path / "plan", benchmark="ragbench")
