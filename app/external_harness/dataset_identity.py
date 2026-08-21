"""Cross-platform content identity for JSON evaluation datasets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def canonical_dataset_sha256(path: Path) -> str:
    """Hash parsed JSON, so encoding whitespace and line endings are irrelevant."""

    value = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


__all__ = ["canonical_dataset_sha256"]
