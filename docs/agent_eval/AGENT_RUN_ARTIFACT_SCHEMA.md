# Agent Run Artifact Schema v1

## Purpose

This contract carries the semantic execution record of one Agent evaluation case from a runtime into AI EvalOps. It is
framework-neutral: `framework` identifies the producer, but the shape does not require LangGraph, LangChain, a model
provider, or an MCP implementation.

The authoritative executable contract is `app.agent_eval.schema.AgentRunArtifact`. Consumers that need JSON Schema can
obtain it through `AgentRunArtifact.model_json_schema()`; its versioned wire identifier is
`agent-run-artifact/v1`.

## Top-level fields

| Field | Meaning | Persistence boundary |
| --- | --- | --- |
| `schema_version` | Exact, versioned wire contract | Stored with artifact metadata |
| `run_id`, `case_id`, `session_id` | Producer correlation identities | Cross-checked against EvalOps ownership at ingestion |
| `framework` | Producer label such as `custom-controller` or `langgraph-adapter` | Metadata, never a control-flow dependency |
| `input`, `output` | Structured case input and terminal output | Immutable artifact payload |
| `trajectory` | Ordered semantic Agent events | Immutable artifact payload |
| `retrieval`, `evidence`, `usage`, `terminal`, `metadata` | Optional structured supporting data | Immutable artifact payload |

## Trajectory events

Each event has a stable `event_id`, a semantic `event_type`, optional `step_id`, optional `tool_name`, and a JSON
`payload`. v1 supports `user_message`, `model_step`, `tool_call`, `tool_result`, `evidence_admission`,
`evidence_rejection`, `claim`, `citation`, and `terminal_state`.

The contract deliberately does not prescribe provider request bodies, model-chain internals, or framework graph nodes.
Adapters map those details into semantic events or preserve them only inside the bounded payload when policy permits.

## Versioning and integrity

Breaking changes require a new `schema_version`; v1 readers reject unknown versions rather than silently accepting a
different meaning. EvalOps computes SHA-256 over canonical JSON (sorted keys, compact separators, UTF-8) and stores
large payloads through the existing content-addressed artifact backend. PostgreSQL stores only ownership, version and
content metadata.

## Sensitive-data rule

An artifact may contain evaluation content, so it is tenant-scoped and handled by the artifact access contract. Prompt
text, document bodies, credentials, authorization headers and raw tool secrets must not be copied into OpenTelemetry
attributes or Prometheus labels. Runtime adapters are responsible for redaction before ingestion where their source
events include secrets.

## Example

```json
{
  "schema_version": "agent-run-artifact/v1",
  "run_id": "run-001",
  "case_id": "case-001",
  "session_id": "session-001",
  "framework": "custom-controller",
  "input": {"message": "Where is the handbook?"},
  "output": {"answer": "In the engineering drive."},
  "trajectory": [
    {"event_id": "1", "event_type": "user_message", "payload": {}},
    {"event_id": "2", "event_type": "tool_call", "tool_name": "search_documents", "payload": {}},
    {"event_id": "3", "event_type": "terminal_state", "payload": {"reason": "answer"}}
  ],
  "terminal": {"state": "answer"}
}
```
