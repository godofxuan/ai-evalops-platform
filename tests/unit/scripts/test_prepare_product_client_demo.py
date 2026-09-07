import hashlib
import json
from uuid import uuid4

import httpx
import pytest

from app.product_experiments.client import ProductAPIClient
from app.product_experiments.dataset_mapping import map_product_dataset
from scripts.prepare_product_client_demo import prepare_dataset


async def test_prepare_captures_actual_ids_and_distinct_hashes(tmp_path):
    raw = json.dumps(
        [
            {"case_id": f"q{i}", "category": "qa", "prompt": "q", "reference_answer": "synthetic"}
            for i in range(2)
        ]
    ).encode()
    digest = hashlib.sha256(raw).hexdigest()
    mapped = map_product_dataset(raw, expected_sha256=digest)
    dataset_id, version_id = uuid4(), uuid4()
    calls = []

    def api(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer synthetic-test-key"
        if len(calls) == 1:
            assert request.url.path == "/api/v1/datasets"
            return httpx.Response(
                201,
                json={
                    "id": str(dataset_id),
                    "name": "demo",
                    "description": None,
                    "created_at": "2026-09-07T00:00:00Z",
                },
            )
        assert request.url.path == f"/api/v1/datasets/{dataset_id}/versions"
        assert mapped.dataset.content in request.content
        return httpx.Response(
            201,
            json={
                "id": str(version_id),
                "dataset_id": str(dataset_id),
                "version": 1,
                "schema_version": "1.0",
                "sha256": mapped.dataset.sha256,
                "case_count": 2,
                "artifact_id": str(uuid4()),
                "created_at": "2026-09-07T00:00:00Z",
            },
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(api)) as http,
        ProductAPIClient("https://evalops.example", "synthetic-test-key", http=http) as client,
    ):
        result = await prepare_dataset(
            client,
            raw_dataset=raw,
            expected_sha256=digest,
            output_dir=tmp_path / "demo",
            name="demo",
        )
        assert result is not None and result.id == version_id
        with pytest.raises(FileExistsError):
            await prepare_dataset(
                client,
                raw_dataset=raw,
                expected_sha256=digest,
                output_dir=tmp_path / "demo",
                name="demo",
            )
    assert len(calls) == 2
    receipt = json.loads((tmp_path / "demo" / "dataset-version.json").read_bytes())
    assert receipt["id"] == str(version_id) and receipt["dataset_id"] == str(dataset_id)
    assert receipt["sha256"] != digest
    assert (tmp_path / "demo" / "cases.json").read_bytes() == raw
    assert (tmp_path / "demo" / "normalized.jsonl").read_bytes() == mapped.dataset.content
    assert all("synthetic-test-key" not in p.read_text() for p in (tmp_path / "demo").iterdir())
