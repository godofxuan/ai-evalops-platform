# Remediation Matrix

`VERIFIED` requires an executed relevant test. New external-service paths remain `PARTIALLY_VERIFIED` until remote CI.

| Finding | Original severity | Status | Code evidence | Test evidence | CI evidence | Remaining limitation |
| --- | --- | --- | --- | --- | --- | --- |
| Full-Run cases polluted common-case gate | P0 | VERIFIED | `app/agent_eval/regression.py` | focused regression tests passed locally | NOT_VERIFIED_IN_REMOTE_CI | Statistical adequacy remains caller policy |
| Zero/missing/small evidence could pass | P0 | VERIFIED | regression gate/schema | zero intersection, exact mismatch, one-sample tests passed | NOT_VERIFIED_IN_REMOTE_CI | Defaults do not prove a universal threshold |
| Comparison dynamically selected latest evidence | P0 | PARTIALLY_VERIFIED | migration 0021, regression service | PostgreSQL replay test written | NOT_VERIFIED_IN_REMOTE_CI | Needs real migrated DB run |
| Human Review source collision | P0 | PARTIALLY_VERIFIED | migration 0022, review service | ordinary/Agent/replay workflow test written | NOT_VERIFIED_IN_REMOTE_CI | Needs real migrated DB run |
| First reviewer saw machine result | P1 | PARTIALLY_VERIFIED | separate evaluator evidence and service visibility | staged three-reviewer test written | NOT_VERIFIED_IN_REMOTE_CI | Content itself can still anchor a reviewer |
| Nested runtime identifiers entered packets | P1 | VERIFIED | `review_packet.py` | recursive allowlist test passed | NOT_VERIFIED_IN_REMOTE_CI | Selected fields omitted, not anonymous |
| MCP startup-only authentication | P0 | PARTIALLY_VERIFIED | `mcp_server.py`, `mcp_stdio.py` | official client unit passes; subprocess test written | NOT_VERIFIED_IN_REMOTE_CI | Local stdio only; host env risk |
| No real Agent HTTP/MinIO boundary test | P0 | PARTIALLY_VERIFIED | existing public routes/services | full HTTP/MinIO test written | NOT_VERIFIED_IN_REMOTE_CI | Requires CI services |
| Concurrent Agent identity not publicly tested | P1 | PARTIALLY_VERIFIED | artifact/evaluator upserts | 20+20 HTTP concurrency test written | NOT_VERIFIED_IN_REMOTE_CI | One CI environment is not scale evidence |
| Agent evidence tables lacked RLS | P1 | PARTIALLY_VERIFIED | migration 0023 | restricted-role test written | NOT_VERIFIED_IN_REMOTE_CI | Runtime/migration roles not split in Compose |
| Artifact reference could mismatch tenant/Run/SHA | P0 | PARTIALLY_VERIFIED | composite FK in model/migration 0023 | constraint/integration coverage written | NOT_VERIFIED_IN_REMOTE_CI | Must validate migration on PostgreSQL |
| Rolled-back DB could leave object orphan | P1 | PARTIALLY_VERIFIED | reconciler, storage listing, migration 0024 | rollback/grace/race/shared/retry test written | NOT_VERIFIED_IN_REMOTE_CI | Reconciliation, not atomicity |
| Producer claims looked verified | P1 | VERIFIED | evaluator provenance and migration 0025 | provenance tests passed locally | NOT_VERIFIED_IN_REMOTE_CI | No verified extractor exists yet |
| Nonfunctional evaluator config changed identity | P1 | VERIFIED | strict config rejection | evaluator config test passed | NOT_VERIFIED_IN_REMOTE_CI | Future configs need typed schemas |
| Invalid numeric evidence accepted | P1 | VERIFIED | artifact schema validator | negative/NaN/Infinity tests passed | NOT_VERIFIED_IN_REMOTE_CI | Domain-specific upper bounds not defined |
| README/resume exceeded evidence | P1 | DOC_ONLY | README and resume evidence map | manual review | NOT_VERIFIED_IN_REMOTE_CI | Must update CI URLs after success |
