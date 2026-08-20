# Remediation Matrix

`VERIFIED` requires an executed relevant test. Remote evidence below is bound to successful run
[`32282462281`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32282462281) at source `22fda89`.

| Finding | Original severity | Status | Code evidence | Test evidence | CI evidence | Remaining limitation |
| --- | --- | --- | --- | --- | --- | --- |
| Full-Run cases polluted common-case gate | P0 | VERIFIED | `app/agent_eval/regression.py` | focused regression plus full suite | run passed | Statistical adequacy remains caller policy |
| Zero/missing/small evidence could pass | P0 | VERIFIED | regression gate/schema | zero intersection, exact mismatch, one-sample tests | run passed | Defaults do not prove a universal threshold |
| Comparison dynamically selected latest evidence | P0 | VERIFIED | migration 0021, regression service | PostgreSQL immutable replay | Agent workflow passed | New evidence does not mutate stored comparison |
| Human Review source collision | P0 | VERIFIED | migration 0022, review service | ordinary/Agent/replay PostgreSQL workflow | Agent workflow passed | Multiple source-specific tasks are intentional |
| First reviewer saw machine result | P1 | VERIFIED | separate evaluator evidence and service visibility | staged three-reviewer test | Agent workflow passed | Content itself can still anchor a reviewer |
| Nested runtime identifiers entered packets | P1 | VERIFIED | `review_packet.py` | recursive allowlist test | run passed | Selected fields omitted, not anonymous |
| MCP startup-only authentication | P0 | VERIFIED | `mcp_server.py`, `mcp_stdio.py` | official client plus real stdio/PostgreSQL revoke | MCP step passed | Local stdio only; host env risk |
| No real Agent HTTP/MinIO boundary test | P0 | VERIFIED | public routes/services | real lifespan/auth/PostgreSQL/MinIO test | HTTP/MinIO step passed | One CI topology is not production evidence |
| Concurrent Agent identity not publicly tested | P1 | VERIFIED | artifact/evaluator upserts | 20+20 concurrent HTTP calls | HTTP/MinIO step passed | One CI environment is not scale evidence |
| Agent evidence tables lacked RLS | P1 | VERIFIED | migration 0023 | restricted `NOBYPASSRLS` role | Agent workflow passed | Runtime/migration roles not split in Compose |
| Artifact reference could mismatch tenant/Run/SHA | P0 | VERIFIED | composite FK in model/migration 0023 | PostgreSQL constraint coverage | Agent workflow and migrations passed | Deployment still needs restricted runtime role |
| Rolled-back DB could leave object orphan | P1 | VERIFIED | reconciler, storage listing, migration 0024 | rollback/grace/race/shared/retry | reconciliation step passed | Reconciliation, not atomicity |
| Producer claims looked verified | P1 | VERIFIED | evaluator provenance and migration 0025 | provenance tests | full suite/migrations passed | No verified extractor exists yet |
| Nonfunctional evaluator config changed identity | P1 | VERIFIED | strict config rejection | evaluator config test | full suite passed | Future configs need typed schemas |
| Invalid numeric evidence accepted | P1 | VERIFIED | artifact schema validator | negative/NaN/Infinity tests | full suite passed | Domain-specific upper bounds not defined |
| README/resume exceeded evidence | P1 | DOC_ONLY | README and resume evidence map | manual evidence audit | docs bound to successful run | Claims remain deliberately qualified |
