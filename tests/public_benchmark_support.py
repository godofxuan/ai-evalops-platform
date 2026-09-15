"""One source gate shared by optional fast tests and mandatory release evidence."""

import os
from pathlib import Path

import pytest

from app.public_benchmarks.bfcl import validate_sources


def required_bfcl_root() -> Path:
    root = Path(
        os.environ.get(
            "EVALOPS_BFCL_ROOT",
            str(Path(__file__).resolve().parents[1] / "artifacts/public-benchmark-20260912/bfcl"),
        )
    )
    if not all((root / name).is_file() for name in ("manifest.json", "cases.json")):
        message = "BFCL evidence missing; run scripts.prepare_bfcl_pilot --download"
        if os.getenv("EVALOPS_RELEASE_EVIDENCE") == "1":
            pytest.fail(message)
        pytest.skip(message + " (optional fast-unit only)")
    validate_sources(root / "upstream")
    return root
