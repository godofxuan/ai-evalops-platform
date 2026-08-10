# Evidence Gate Hardening Context

## Why this stage exists

Candidate 3 had bounded correctness/fairness evidence, but the release remained `NOT_READY` because
the frozen w4→w8 gate failed in three distributions. Before attributing that regression, this stage
closed three ways that evidence could be internally consistent yet insufficiently independent, and
one real `SKIP LOCKED` state-machine bug.

Starting branch and SHA were `codex/evidence-gate-1` and
`01626d93799b93187fc0c6f340ca3a277e0da7f8`. A fetch confirmed local and remote matched and the
working tree was clean. The locked project environment is `.venv` Python 3.12.13; the system Python
is 3.13.5 and is not the project environment. Local PostgreSQL, `psql`, Docker and `uv` CLI were not
available, so real database verdicts came from GitHub Actions.

## Baseline

- System `python -m pip check`: exit 0, 1.164 s, but only describes the system Python.
- `python -m compileall app scripts tests`: exit 0, 2.166 s.
- System-Python pytest: exit 4 with 51 collection errors because project dependencies and
  `pytest-asyncio` were absent. This was an environment-selection failure, not a project regression.
- `.venv\\Scripts\\python.exe -m pytest -q`: exit 0; 676 passed, 28 skipped, 405.15 s.
- The skipped baseline includes real PostgreSQL, Redis and MinIO integration tests.

## Frozen boundaries

Historical targeted workflow `31352270523` remains `NEGATIVE_SCALING`; v0.1.0 remains
`NOT_READY`; PR #1 remains Draft; capacity/same-runner/fault/formal downstream stages remain
`NOT_RUN_STOPPED`. This stage did not change the 0.95 threshold, q1000/b1 workload, Worker levels,
repetitions, median rule or historical evidence.

## Work sequence

1. establish a clean baseline and inspect real EXPLAIN plans;
2. commit fail-closed RED tests;
3. independently parse raw EXPLAIN in the assessor;
4. bind targeted CSV metadata to fullmatched arm IDs and validate numeric domains;
5. make no-false-empty an automatic schema-v2 and targeted blocker;
6. reproduce and fix the locked-Job false-empty interleaving in real PostgreSQL;
7. preregister, implement and overhead-gate diagnostic instrumentation;
8. stop after attribution, without implementing another scheduler candidate.
