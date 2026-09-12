"""Download revision-checked public rows, freeze an ID-selected pilot, and rescore."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from app.core.strict_json import decode_evidence_json
from app.public_benchmarks.ragbench import (
    DATASET,
    DOMAINS,
    REVISION,
    SAMPLING_RULE,
    canonical_bytes,
    published_prediction_report,
    select_pilot,
)


def load_source_cache(source: Path) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Replay downloaded raw pages with exact IDs, page continuity, hashes, and revision."""
    receipts = decode_evidence_json((source / "receipts.json").read_bytes())
    if not isinstance(receipts, list):
        raise ValueError("Invalid source receipts")
    rows_by_domain: dict[str, list[dict[str, Any]]] = {domain: [] for domain in DOMAINS}
    totals: dict[str, int] = {}
    seen_files: set[str] = set()
    for receipt in receipts:
        name = receipt["file"]
        candidates = [
            domain
            for domain in DOMAINS
            if name == f"{domain}-test-{len(rows_by_domain[domain]):05d}.json"
        ]
        if len(candidates) != 1 or name in seen_files:
            raise ValueError("Invalid source filename, duplicate, or page sequence")
        domain = candidates[0]
        seen_files.add(name)
        if receipt["response_revision"] != REVISION:
            raise ValueError("Source revision mismatch")
        raw = (source / name).read_bytes()
        if len(raw) > 20_000_000 or hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
            raise ValueError("Source page hash mismatch or size limit")
        payload = decode_evidence_json(raw)
        if not isinstance(payload, dict) or payload.get("partial"):
            raise ValueError("Invalid or partial source payload")
        total = payload["num_rows_total"]
        if type(total) is not int or not 1 <= total <= 10_000:
            raise ValueError("Invalid source total")
        if domain in totals and totals[domain] != total:
            raise ValueError("Source total changed across pages")
        totals[domain] = total
        for entry in payload["rows"]:
            if entry["row_idx"] != len(rows_by_domain[domain]) or entry.get("truncated_cells"):
                raise ValueError("Truncated or misindexed source data")
            rows_by_domain[domain].append(entry["row"])
    if any(len(rows_by_domain[domain]) != totals.get(domain) for domain in DOMAINS):
        raise ValueError("Incomplete source cache")
    return rows_by_domain, receipts


def fetch_domain(
    domain: str, destination: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    offset = 0
    total = 1
    while offset < total:
        query = urllib.parse.urlencode(
            {
                "dataset": DATASET,
                "config": domain,
                "split": "test",
                "offset": offset,
                "length": 100,
                "revision": REVISION,
            }
        )
        url = f"https://datasets-server.huggingface.co/rows?{query}"
        request = urllib.request.Request(url, headers={"User-Agent": "EvalOps-public-pilot/1.0"})
        with urllib.request.urlopen(request, timeout=90) as response:
            revision = response.headers.get("x-revision")
            if revision != REVISION:
                raise ValueError(
                    "Official rows response revision does not match the frozen revision"
                )
            raw = response.read(20_000_001)
        if len(raw) > 20_000_000:
            raise ValueError("Public source page exceeds the bounded download limit")
        payload = json.loads(raw)
        if payload.get("partial"):
            raise ValueError("Source API reports a partial page")
        total = payload["num_rows_total"]
        if type(total) is not int or not 1 <= total <= 10_000:
            raise ValueError("Unexpected source row count")
        page = payload["rows"]
        if not page:
            raise ValueError("Missing source rows")
        for index, entry in enumerate(page):
            if entry["row_idx"] != offset + index or entry.get("truncated_cells"):
                raise ValueError(
                    "Truncated or misindexed source data; no silent text truncation allowed"
                )
            rows.append(entry["row"])
        name = f"{domain}-test-{offset:05d}.json"
        (destination / name).write_bytes(raw)
        receipts.append(
            {
                "file": name,
                "url": url,
                "response_revision": revision,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "byte_size": len(raw),
                "source_row_count": total,
                "page_row_count": len(page),
            }
        )
        offset += len(page)
    return rows, receipts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--source-dir", type=Path, help="Replay saved official response bytes offline"
    )
    arguments = parser.parse_args()
    output = arguments.output_dir
    if output.exists():
        raise ValueError("Output directory already exists; never overwrite a frozen pilot")
    output.mkdir(parents=True)
    source = output / "source"
    source.mkdir()
    rows_by_domain: dict[str, list[dict[str, Any]]] = {}
    receipts: list[dict[str, Any]] = []
    if arguments.source_dir:
        rows_by_domain, receipts = load_source_cache(arguments.source_dir)
        for receipt in receipts:
            (source / receipt["file"]).write_bytes(
                (arguments.source_dir / receipt["file"]).read_bytes()
            )
    else:
        for domain in DOMAINS:
            rows, source_receipts = fetch_domain(domain, source)
            rows_by_domain[domain] = rows
            receipts.extend(source_receipts)
    (source / "receipts.json").write_bytes(canonical_bytes(receipts))
    cases = select_pilot(rows_by_domain)
    data = canonical_bytes(cases)
    (output / "cases.json").write_bytes(data)
    manifest = {
        "schema_version": "evalops.ragbench-public-pilot/1.0",
        "dataset": DATASET,
        "revision": REVISION,
        "license": "cc-by-4.0",
        "split": "test",
        "source": "https://huggingface.co/datasets/galileo-ai/ragbench",
        "sampling_rule": SAMPLING_RULE,
        "sample_count": len(cases),
        "per_domain": 100,
        "source_counts": {domain: len(rows) for domain, rows in rows_by_domain.items()},
        "source_unique_question_counts": {
            domain: len({row["id"] for row in rows}) for domain, rows in rows_by_domain.items()
        },
        "cases_sha256": hashlib.sha256(data).hexdigest(),
        "receipts": receipts,
        "label_origin": "PUBLIC_AUTOMATED_ANNOTATION",
        "human_review": "NOT_RUN",
        "model_calls": 0,
        "formal_quality_claim_allowed": False,
        "selection_uses_labels_or_predictions": False,
    }
    (output / "manifest.json").write_bytes(canonical_bytes(manifest))
    (output / "published-predictions-report.json").write_bytes(
        canonical_bytes(published_prediction_report(cases))
    )
    print(
        json.dumps(
            {
                "status": "PUBLIC_PILOT_FROZEN",
                "case_count": len(cases),
                "output_dir": str(output),
                "cases_sha256": manifest["cases_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
