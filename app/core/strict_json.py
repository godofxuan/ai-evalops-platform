"""Unambiguous bounded-depth JSON parsing for untrusted evidence."""

import json
from typing import Any


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON constant")


def decode_evidence_json(payload: bytes | str) -> Any:
    """Caller owns byte limits. Check nesting before recursive JSON decoding."""
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    depth = 0
    quoted = False
    escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > 64:
                raise ValueError("JSON depth limit exceeded")
        elif character in "]}":
            depth -= 1
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
