# Agent Eval Resume Evidence

Use only claims backed by source and test command. This vNext work is feature evidence, not production capacity evidence,
and does not supersede the v0.1 scheduler release decision.

| Claim | Source | Command | Allowed wording | Forbidden wording |
| --- | --- | --- | --- | --- |
| Framework-neutral Agent trajectory contract | `app/agent_eval/schema.py`, commit `27ead40` | `python -m pytest tests/unit/agent_eval/test_artifact_schema.py -q` | “Defined a versioned, framework-neutral Agent execution artifact contract.” | “Supports every Agent framework natively.” |
| Tenant-scoped immutable trajectory ingestion | `app/agent_eval/service.py`, migration `20260819_0019`, commit `9fe1e13` | `python -m pytest tests/api/test_agent_artifacts.py tests/unit/persistence/test_agent_execution_artifact_migration.py -q` | “Added tenant-scoped, content-addressed Agent trajectory ingestion.” | “Exactly-once Agent execution.” |
| Deterministic trajectory evaluation and regression gate | `app/agent_eval/evaluators.py`, `regression.py`, commit `5806c4a` | `python -m pytest tests/unit/agent_eval/test_evaluators.py tests/unit/agent_eval/test_failure_and_regression.py -q` | “Built deterministic tool-use, trajectory and regression evaluators with configurable gates.” | “Achieved universal quality thresholds.” |

Metrics are fixture/test evidence only until a frozen Agent benchmark produces source-bound results. Do not quote v0.1
scheduler throughput or fairness measurements as Agent Runtime metrics.
