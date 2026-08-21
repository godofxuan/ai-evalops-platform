# Automated result

Status: **INPUT_BLOCKED**

| Input | Exact SHA | Harness 1.0 at SHA |
|---|---|---:|
| Baseline A | `909a9710932c6c4744c462db0e33ed0d222ecb1a` | No |
| Candidate B | `e848d8e6090267b28d351758fe8d3cb557dcd586` | Yes |

The candidate harness was run locally in deterministic mode and returned a valid `enterprise.agent-harness-result/1.0`. The baseline tree check `git cat-file -e <sha>:app/agent_runtime/harness_contract.py` returned 128. Therefore there is no symmetric stable endpoint for A and B.

Task success delta, groundedness delta, citation correctness delta, tool correctness delta, latency delta, token delta, cost delta, failure-rate delta, bootstrap interval, and per-category A/B metrics are **not computed**. Zeroes would be false measurements. The paired-statistics implementation is tested, including common IDs and A-only/B-only reporting, but no formal A/B input was supplied to it.
