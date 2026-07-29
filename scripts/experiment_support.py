import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx

TERMINAL_RUN_STATUSES = {
    "succeeded",
    "partially_succeeded",
    "failed",
    "cancelled",
}


class ExperimentError(RuntimeError):
    """An experiment precondition or API contract failed."""


class ExperimentClient:
    def __init__(
        self,
        *,
        api_url: str,
        api_key_env: str,
        timeout_seconds: float,
    ) -> None:
        api_key = os.getenv(api_key_env)
        if api_key is None:
            raise ExperimentError(f"required environment variable {api_key_env} is unset")
        self._client = httpx.AsyncClient(
            base_url=api_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def __aenter__(self) -> "ExperimentClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.aclose()

    async def create_dataset_version(
        self,
        *,
        name_prefix: str,
        cases: list[dict[str, Any]],
    ) -> str:
        dataset = await self._request_json(
            "POST",
            "/api/v1/datasets",
            json={"name": f"{name_prefix}-{uuid4().hex[:12]}"},
        )
        content = b"".join(
            json.dumps(case, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
            for case in cases
        )
        version = await self._request_json(
            "POST",
            f"/api/v1/datasets/{dataset['id']}/versions",
            files={"file": ("experiment.jsonl", content, "application/x-ndjson")},
        )
        return str(version["id"])

    async def create_run(
        self,
        *,
        dataset_version_id: str,
        target_config: dict[str, Any],
        evaluator_config: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            "/api/v1/runs",
            headers={"Idempotency-Key": idempotency_key or f"experiment-{uuid4().hex}"},
            json={
                "dataset_version_id": dataset_version_id,
                "target": {
                    "type": "mock",
                    "version": "phase9-experiment-v1",
                    "config": target_config,
                },
                "evaluator": {
                    "type": "basic_answer",
                    "version": "phase9-experiment-v1",
                    "config": evaluator_config or {"max_attempts": 3},
                },
            },
        )

    async def wait_for_run(
        self,
        run_id: str,
        *,
        poll_seconds: float,
        deadline_seconds: float,
    ) -> tuple[dict[str, Any], float]:
        started = perf_counter()
        while True:
            snapshot = await self._request_json("GET", f"/api/v1/runs/{run_id}")
            if snapshot["status"] in TERMINAL_RUN_STATUSES:
                return snapshot, perf_counter() - started
            if perf_counter() - started >= deadline_seconds:
                raise ExperimentError(f"run {run_id} did not finish before the deadline")
            await asyncio.sleep(poll_seconds)

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._request_json("GET", f"/api/v1/runs/{run_id}")

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        return await self._request_json("POST", f"/api/v1/runs/{run_id}/cancel")

    async def list_all_cases(self, run_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params = {"limit": "200", "sort": "case_id"}
            if cursor is not None:
                params["cursor"] = cursor
            page = await self._request_json(
                "GET",
                f"/api/v1/runs/{run_id}/cases",
                params=params,
            )
            items.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return items

    async def compare_runs(self, left_run_id: str, right_run_id: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            "/api/v1/runs/compare",
            params={"left_run_id": left_run_id, "right_run_id": right_run_id},
        )

    async def concurrent_create(
        self,
        *,
        count: int,
        dataset_version_id: str,
        idempotency_key: str,
    ) -> list[httpx.Response]:
        payload = {
            "dataset_version_id": dataset_version_id,
            "target": {
                "type": "mock",
                "version": "phase9-concurrency-v1",
                "config": {"answer": "mock answer"},
            },
            "evaluator": {
                "type": "basic_answer",
                "version": "phase9-concurrency-v1",
                "config": {"max_attempts": 3},
            },
        }
        return await asyncio.gather(
            *(
                self._client.post(
                    "/api/v1/runs",
                    headers={"Idempotency-Key": idempotency_key},
                    json=payload,
                )
                for _ in range(count)
            )
        )

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._client.request(method, path, **kwargs)
        if not response.is_success:
            request_id = response.headers.get("X-Request-ID", "absent")
            raise ExperimentError(
                f"{method} {path} returned HTTP {response.status_code}; request_id={request_id}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ExperimentError(f"{method} {path} returned a non-object response")
        return payload


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def experiment_envelope(*, experiment: str, configuration: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "experiment": experiment,
        "started_at": datetime.now(UTC).isoformat(),
        "configuration": configuration,
        "status": "running",
        "results": [],
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ExperimentError(f"refusing to overwrite existing result file: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
