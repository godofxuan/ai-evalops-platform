# Agent Eval Resume Evidence

Use only claims backed by source and test command. This vNext work is feature evidence, not production capacity evidence,
and does not supersede the v0.1 scheduler release decision.

| Claim | Source | Command | Allowed wording | Forbidden wording |
| --- | --- | --- | --- | --- |
| Framework-neutral Agent trajectory contract | `app/agent_eval/schema.py`, commit `27ead40` | `python -m pytest tests/unit/agent_eval/test_artifact_schema.py -q` | “Defined a versioned, framework-neutral Agent execution artifact contract.” | “Supports every Agent framework natively.” |
| Tenant-scoped immutable trajectory ingestion | `app/agent_eval/service.py`, migration `20260819_0019`, commit `9fe1e13` | `python -m pytest tests/api/test_agent_artifacts.py tests/unit/persistence/test_agent_execution_artifact_migration.py -q` | “Added tenant-scoped, content-addressed Agent trajectory ingestion.” | “Exactly-once Agent execution.” |
| Deterministic trajectory evaluation and regression gate | `app/agent_eval/evaluators.py`, `regression.py`, commit `5806c4a` | `python -m pytest tests/unit/agent_eval/test_evaluators.py tests/unit/agent_eval/test_failure_and_regression.py -q` | “Built deterministic tool-use, trajectory and regression evaluators with configurable gates.” | “Achieved universal quality thresholds.” |
| Persisted evaluator evidence and Run gate | migration `20260819_0020`, commit `12484ec` | `python -m pytest tests/api/test_agent_artifacts.py tests/api/test_agent_regression.py tests/unit/persistence/test_agent_evaluation_result_migration.py -q` | “Persisted version/config-bound Agent evaluator evidence and compared tenant-scoped Runs through configurable gates.” | “Exactly-once evaluation or universal thresholds.” |
| Authenticated MCP stdio control plane | `mcp_stdio.py`, `mcp_service_adapter.py`, commit `c85b3de` | `python -m pytest tests/unit/agent_eval/test_mcp_server.py tests/unit/agent_eval/test_mcp_service_adapter.py -q` | “Exposed seven EvalOps tools through the official MCP SDK while reusing the existing API-key Principal and services.” | “Public production MCP HTTP service.” |
| Agent evidence in human review | `reviews/service.py`, commit `66b69d6` | `python -m pytest tests/api/test_reviews.py tests/unit/agent_eval/test_review_packet.py -q` | “Routed bounded, identity-blinded Agent trajectories into the existing double-review/adjudication workflow.” | “Eliminated reviewer bias or proved reviewer identity.” |
| Fixed adapter-contract benchmark | fixture and evidence, commit `27fb175` | `python -m scripts.run_agent_adapter_benchmark` | “Built a deterministic eight-family adapter compatibility benchmark with source-bound evidence.” | “Benchmarked live LangGraph performance.” |

The `0.875` success and approximately `83 ms` p95 values are fixed replay evidence only. Do not present them as live
Agent, LangGraph, scheduler, production-capacity or model-quality measurements. Do not quote v0.1 scheduler throughput
or fairness measurements as Agent Runtime metrics.
