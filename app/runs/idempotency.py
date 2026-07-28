import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_request_hash(payload: Mapping[str, Any]) -> str:
    canonical_json = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
