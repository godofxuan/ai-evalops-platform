# MCP Eval Control Plane

## Purpose

The MCP surface gives an Agent development client a controlled development loop:

```text
developer changes Agent → submit_evaluation → EvalOps Run → Worker execution
→ get_run_status → list_failed_cases → get_case_trajectory → compare_runs
```

`app.agent_eval.control_plane.McpEvalControlPlane` defines seven tools: `submit_evaluation`, `get_run_status`,
`list_failed_cases`, `get_case_result`, `get_case_trajectory`, `compare_runs` and `get_regression_summary`.

`app.agent_eval.mcp_server.build_mcp_server` exposes those tools through the official MCP Python SDK v2.
`app.agent_eval.mcp_stdio` is the runnable local transport; launch it with:

```powershell
$env:EVALOPS_MCP_API_KEY = "evk_..."
uv run python -m app.agent_eval.mcp_stdio
```

## Security boundary

The stdio entry point requires `EVALOPS_MCP_API_KEY`, validates it through the existing scrypt API-key lookup and binds
the resulting server-derived `Principal` to the MCP server before accepting tool calls. Missing, expired, revoked,
disabled-tenant or concurrently revoked credentials fail through the existing authentication contract. Tool inputs do
not accept `tenant_id`.

`EvalOpsMcpServiceAdapter` delegates to the existing Run, Result, Agent artifact and Agent regression services. It does
not query ORM tables or own a second authorization mechanism.

This design keeps PostgreSQL authoritative and preserves API-key audit behavior. It also allows stdio, HTTP or a future
official MCP SDK adapter to share one tested control-plane contract instead of reimplementing business logic.

## Initial tool contract

Tool inputs are tenant-free because tenant identity comes from the authenticated Principal. Tool responses are service
responses only; no prompt, document or credential payload is added to trace attributes or Prometheus labels.

The current runnable transport is stdio. Streamable HTTP is deliberately not mounted: the official SDK supports it, but
shipping it requires a separately tested OAuth/resource-server or equivalent deployment authentication design. This
repository does not turn a local API key environment variable into an unauthenticated shared network listener.

The official in-memory MCP client test validates discovery and tool calls without mocking protocol framing. The real
PostgreSQL workflow test validates the services behind trajectory, evaluation and regression operations.
