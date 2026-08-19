# MCP Eval Control Plane

## Purpose

The MCP surface gives an Agent development client a controlled development loop:

```text
developer changes Agent → submit_evaluation → EvalOps Run → Worker execution
→ get_run_status → list_failed_cases → get_case_trajectory → compare_runs
```

`app.agent_eval.control_plane.McpEvalControlPlane` defines seven tools: `submit_evaluation`, `get_run_status`,
`list_failed_cases`, `get_case_result`, `get_case_trajectory`, `compare_runs` and `get_regression_summary`.

## Security boundary

The control plane is transport-independent. A real MCP transport adapter must authenticate its caller first and
construct the existing server-derived `Principal`; the tool dispatcher delegates to the existing Run, Result and Agent
artifact service layer. It must not connect directly to ORM tables, accept tenant IDs from tool arguments or invent a
second authorization mechanism.

This design keeps PostgreSQL authoritative and preserves API-key audit behavior. It also allows stdio, HTTP or a future
official MCP SDK adapter to share one tested control-plane contract instead of reimplementing business logic.

## Initial tool contract

Tool inputs are tenant-free because tenant identity comes from the authenticated Principal. Tool responses are service
responses only; no prompt, document or credential payload is added to trace attributes or Prometheus labels.

The present core is intentionally not a public unauthenticated network listener. Exposing one before choosing and
testing an authenticated MCP transport would violate the project’s existing auth boundary.
