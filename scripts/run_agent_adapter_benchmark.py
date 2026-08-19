"""Generate deterministic, source-bound evidence for the Agent adapter contract benchmark."""

import argparse
from pathlib import Path

from app.agent_eval.benchmark import (
    canonical_benchmark_evidence_bytes,
    run_adapter_comparison,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "benchmarks" / "agent_eval_v1" / "cases.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "agent_eval" / "adapter_comparison_evidence.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    evidence = run_adapter_comparison(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_benchmark_evidence_bytes(evidence) + b"\n")
    print(f"wrote deterministic Agent adapter evidence: {args.output}")


if __name__ == "__main__":
    main()
