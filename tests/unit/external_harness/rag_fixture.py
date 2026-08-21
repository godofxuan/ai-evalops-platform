import copy
import hashlib
import json
from typing import Any

from app.external_harness.rag_harness import RagHarnessResultV1


def seal_rag_result(source: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(source)
    artifact = result["trajectory_artifact"]
    events = artifact["trajectory"]
    previous: str | None = None
    for event in events:
        event["previous_hash"] = previous
        event["event_hash"] = "0" * 64
    artifact["source_trajectory_root_hash"] = "0" * 64
    artifact["artifact_sha256"] = "0" * 64

    parsed = RagHarnessResultV1.model_validate(result)
    for index, event in enumerate(parsed.trajectory_artifact.trajectory):
        event_with_link = event.model_copy(update={"previous_hash": previous})
        digest = _digest(event_with_link.model_dump(mode="json", exclude={"event_hash"}))
        events[index]["previous_hash"] = previous
        events[index]["event_hash"] = digest
        previous = digest
    artifact["source_trajectory_root_hash"] = previous

    parsed = RagHarnessResultV1.model_validate(result)
    artifact["artifact_sha256"] = _digest(
        parsed.trajectory_artifact.model_dump(mode="json", exclude={"artifact_sha256"})
    )
    return result


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()
