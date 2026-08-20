# Resume-Safe Claims

## Safe now

- Designed PostgreSQL-backed Run/Job/Attempt orchestration with lease heartbeat, fenced commits and Reaper recovery.
- Defined a versioned framework-neutral Agent trajectory contract with canonical JSON/SHA-256 content identity.
- Persisted reported/derived metric provenance instead of describing producer claims as verified.
- Preserved the historical 4→8 Worker negative-scaling result instead of selecting favorable measurements.

## Safe with qualification

- Implemented and remotely verified fail-closed common-case regression logic and a PostgreSQL manifest that pins
  artifact/result IDs.
- Implemented source-bound human review packets with staged machine-evidence visibility; this omits selected runtime
  identifiers but does not guarantee anonymity or remove all bias.
- Implemented local MCP stdio per-call credential revalidation and lock-ordered revocation; there is no remote MCP
  network security boundary.
- Added real HTTP/scrypt/PostgreSQL/MinIO and concurrent idempotency tests, executed successfully in final branch CI.
- Added Agent evidence RLS policies and restricted-role tests; Compose runtime/migration credential separation remains.
- Added dry-run-first orphan reconciliation with grace period and reference recheck; PostgreSQL/S3 are not atomic.

## Do not claim

- production-ready, exactly-once, linearly scalable or proven at production scale;
- seven verified evaluators or independent validation of producer truth;
- complete anonymity, elimination of reviewer bias or complete identity blindness;
- all Agent frameworks or a live LangGraph integration benchmark;
- public/remote secure MCP, OAuth MCP or Streamable HTTP;
- atomic database/object-store commit or zero orphan objects;
- complete production RLS deployment-role isolation;
- performance leadership from fixture replay values.
