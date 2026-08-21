from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.external_harness.dataset_identity import canonical_dataset_sha256
from app.external_harness.rag_subprocess import harness_contract_available

BASELINE_SHA = "909a9710932c6c4744c462db0e33ed0d222ecb1a"
CANDIDATE_SHA = "e848d8e6090267b28d351758fe8d3cb557dcd586"
EXPECTED_DATASET_SHA256 = "08ccad71d7c96cdd2d558018b480a1e421abd3781527a828793aa4430d517d11"
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight frozen RAG A/B harness capability")
    parser.add_argument("rag_repo", type=Path)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT / "benchmarks/external_harness_v1/cases.json"
    )
    args = parser.parse_args()
    dataset_hash = canonical_dataset_sha256(args.dataset)
    if dataset_hash != EXPECTED_DATASET_SHA256:
        raise SystemExit("dataset digest does not match the frozen preregistration")
    baseline = harness_contract_available(args.rag_repo, BASELINE_SHA)
    candidate = harness_contract_available(args.rag_repo, CANDIDATE_SHA)
    status = "READY" if baseline and candidate else "INPUT_BLOCKED"
    print(
        json.dumps(
            {
                "status": status,
                "baseline_sha": BASELINE_SHA,
                "candidate_sha": CANDIDATE_SHA,
                "dataset_sha256": dataset_hash,
                "baseline_harness_contract_available": baseline,
                "candidate_harness_contract_available": candidate,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if status == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
