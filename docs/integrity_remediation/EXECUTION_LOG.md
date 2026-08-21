# Integrity Remediation Execution Log

Branch: codex/evalops-integrity-remediation-v1

Base: 5eb1d7eebc4917e32aa0a0617521ae96f5a201d0

Frozen external producer reviewed read-only:
e848d8e6090267b28d351758fe8d3cb557dcd586

## Decision record

### Artifact reconciliation

Problem: the former reconciler checked references, called object storage deletion inside
the database transaction, then removed Blob metadata. This held database locks across
remote I/O and left a time-of-check/time-of-use gap.

Decision: retain Blob tombstones and introduce ACTIVE, DELETE_PENDING, DELETED,
DELETE_FAILED, and RESTORE_REQUIRED. A reconciler claims a bounded database lease,
deletes outside the transaction using the exact scanned object identity, and finalizes
by token CAS in a new transaction. A PostgreSQL trigger rejects references to non-ACTIVE
Blobs. Missing referenced objects become RESTORE_REQUIRED; a missing claimed orphan can
complete as DELETED.

Effect: reference creation and deletion claims are ordered by PostgreSQL, remote storage
I/O no longer runs inside the claim transaction, retries are durable, and object
replacement after scan fails closed for Local and S3/MinIO.

### Fair scheduler

Problem: every successful claim updated the singleton SchedulerCoordination row only to
allocate a diagnostic receipt number.

Decision: preserve the durable fair-round and tenant permit algorithm, add a non-locking
pending-permit fast path, and allocate diagnostic claim receipts from a PostgreSQL
sequence. The singleton row is locked only when a new round may be required.

Effect: unrelated successful claims no longer serialize on diagnostic bookkeeping.
A 1/2/4/8-worker targeted microbenchmark reports latency, throughput, retry, fallback
and lock-diagnostic fields. It is explicitly not a replacement for the frozen formal
scaling protocol and makes no linear-scaling claim.

### External harness integrity

Problem: the RAG adapter trusted producer digest strings and rebuilt only top-level tool
events; Inspect silently discarded unknown events and admitted non-terminal logs.

Decision: recompute the producer event hash chain, root and Artifact digest; verify the
top-level tool projection; preserve every supported semantic event; and publish exact
loss counts. Inspect now has a supported-version/event registry, strict formal mode and
non-gating diagnostic raw mode.

Effect: tampering, duplication, order changes, unknown formal events and partial formal
logs fail closed. Diagnostic partial logs remain useful without becoming release proof.

### Statistical sufficiency

Problem: a paired interval could be produced from one common case and category coverage
was not a first-class gate.

Decision: require at least two cases for any bootstrap, add formal common-case and
per-category policies, report A-only/B-only IDs, and introduce INSUFFICIENT_EVIDENCE.
Any required segment failure makes the aggregate fail.

Effect: the existing nine-case mechanism dataset remains non-formal and cannot generate
a release-quality claim.

### MCP audit delivery

Problem: a successful mutation followed by an audit write failure was returned as a
failed tool call, encouraging a retry after the side effect had already happened.

Decision: reserve a durable outbox row before execution, bind mutation identity to the
tenant/tool/idempotency key, atomically deliver AuditEvent plus outbox completion, and
return operation_result plus audit_delivery_status.

Effect: audit delivery failure returns pending, not a false business failure. Retry
reuses the same call identity and the domain idempotency key prevents duplicate run
creation. Credential authorization is still revalidated before every retry.

### Evidence and supply chain

Problem: the evidence manifest listed documents but did not bind their bytes, and two
GitHub Actions used floating major tags.

Decision: add a non-recursive per-file digest manifest with size, source SHA, schema,
generation time and producing command; verify it in CI; pin official actions to full
commit SHAs. Container image digest pinning is deferred because the Compose image update
policy and supported-platform digests require a separate controlled change.

## Tooling issue

The native apply_patch integration failed before reading files because the Windows
sandbox helper could not refresh. Changes were therefore applied as reviewed unified
diffs through Git/patch, followed by git diff --check, Ruff, mypy and tests. Temporary
patch files were removed immediately.

## Evidence boundaries

- No merge, tag, release, force-push, production deployment, or RAG repository mutation.
- No new 64-arm run and no formal 100-200-case A/B execution.
- No human-review completion was fabricated.
- Historical negative scheduler scaling remains binding until a separately authorized
  formal protocol is run.

## Local validation ledger

| Command/scope | Result | Interpretation |
| --- | --- | --- |
| Ruff format/check over repository | exit 0 | Formatting and lint passed. |
| mypy app scripts tests/integration tests/concurrency | exit 0, 177 source files | CI type-check scope passed. |
| compileall app scripts tests | exit 0 | Python syntax compilation passed. |
| focused Artifact/Harness/MCP/migration/manifest tests | 55 passed | New negative and state-transition tests passed. |
| pytest excluding integration | 855 passed, 38 deselected | Full locally runnable suite passed. |
| offline 0026 upgrade/downgrade SQL tests | passed in the focused set | Migration emits state, trigger, sequence, outbox and reverse DDL. |
| evidence manifest write and verify | exit 0 | Every scoped evidence file rehashed successfully. |
| git diff --check | exit 0 | No whitespace errors at the recorded checkpoint. |
| Integration/concurrency collection | 38 skipped, 0 failed | Required service flags were absent; collection and syntax succeeded, but no real-service pass is claimed. |
| Docker Compose / real MinIO | NOT RUN locally | Docker CLI is unavailable; CI remains authoritative. |
| Real PostgreSQL migration/concurrency/MCP integration | NOT RUN locally | No database URL or local service was available; CI remains authoritative. |

The pytest cache emitted one Windows permission warning for a mojibake-rendered cache path.
It did not affect test execution or results. No skipped integration was relabeled as passed.

## Remote validation and corrective loop

The first pushed candidate was commit
`529562042b0fe848ab0576accf164314a11f606f` on the required branch. GitHub Actions
run `32514058544` completed with `compose-smoke` passing and the main job failing in
exactly one integration step. Formatting, lint, mypy, 855 locally runnable tests,
manifest verification, migration upgrade, scheduler fairness/concurrency, Artifact
ownership/reconciliation, real MinIO, tenant isolation, authenticated Agent workflow,
Redis/outbox, migration downgrade/re-upgrade and application image build all passed.

The only failing step was `Integration - MCP stdio credential revocation`. The new
durable outbox delivery path had changed the externally visible AuditEvent resource
from the stable MCP call identity (`resource_type=mcp_tool`,
`resource_id=UUID(trace_id)`) to its internal delivery row
(`resource_type=mcp_audit_outbox`, `resource_id=outbox.id`). This was a semantic
regression: the outbox is the transport for reliable audit delivery, not the audited
business resource. The existing PostgreSQL + real stdio test caught the resource ID
change; an explicit resource-type assertion was added to preserve the complete
contract.

The corrective change restores the stable MCP audit resource semantics while retaining
the outbox reservation, durable outcome, atomic AuditEvent delivery, retry and
idempotency behavior. Local corrective validation produced:

- MCP server unit tests: 4 passed;
- Ruff on the corrected MCP and test files: passed;
- mypy on `app/agent_eval/mcp_stdio.py`: passed;
- real stdio integration collection: 1 skipped because no local PostgreSQL integration
  environment is configured.

The native patch helper and in-app browser connection both encountered the same Windows
sandbox `helper_unknown_error`; the public GitHub API still supplied exact job/step
outcomes. Full logs required authenticated admin access, but the failure was reproduced
at the already-existing contract assertion by comparing the candidate implementation
with the frozen base semantics. The next GitHub Actions run is the authoritative
red-to-green check for the corrected real-service seam.
