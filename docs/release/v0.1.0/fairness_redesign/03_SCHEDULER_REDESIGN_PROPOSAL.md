# Scheduler redesign proposal

Status: `CANDIDATE_3_SELECTED`; production implementation not yet started

## Problem statement derived from RED

Candidate 2 persists only “Tenant B was selected recently.” It does not persist “Tenant B is still owed one completion in this fairness unit.” Therefore a hot Tenant can receive and complete later turns while B's Phase B is delayed. Candidate 3 must make advancement to the next same-priority admission unit depend on every admitted Tenant reaching a durable terminal scheduler state.

## Alternatives evaluated

### Alternative 1 — Re-couple fair selection and the full Job claim under the Tenant business row

One transaction would rank Tenant heads, lock `Tenant`, lock Job, and write Job/Attempt/Audit/Outbox before releasing the Tenant lock.

- F1/F4/F6: preserves priority, Job locking and fencing.
- F2/F3: prevents two simultaneous claims for one Tenant, but after A1 commits it still permits A2 while B1 is unfinished. A per-Tenant lock alone does not create a cross-Tenant round barrier, so the deterministic RED can still place B after position 2.
- F5/F7: rollback is simple.
- F8: the Tenant business row is held through all claim writes; although not external Worker execution, this recreates the FK hot-row coupling that previously produced difficult lock interactions.
- SQL/locks: fewer round trips, but `Tenant -> Job -> Run/Audit/Outbox` lock scope is broad and Tenant FKs can amplify contention.
- schema/rollback: no new table, but the concurrency semantics do not solve the target invariant.

Decision: rejected because it fails F2, independently of performance.

### Alternative 2 — Ordered durable ticket per claim

A short transaction allocates tickets such as A1=1, B1=2, A2=3. Claim transactions may write concurrently, but ticket 3 cannot become durable before ticket 2.

- F1/F2/F3: can be made strict if commit order is gated by ticket order.
- F4/F6: can retain current Job/fencing writes.
- F5/F7: an allocated ticket whose Worker crashes needs ownership, expiry, takeover, stale-token fencing and recovery.
- F8: either later transactions wait while holding Job/Attempt/Audit/Outbox writes, or a global next-ticket lock spans the full claim transaction. Both are undesirable.
- SQL/locks: one row per claim, predecessor waits, cleanup and retry amplification. Hot global ticket advancement is likely.
- schema/rollback/GC: unbounded ticket history or a correctness-sensitive garbage collector; this becomes a second lease subsystem.

Decision: rejected. It can solve the order but violates the requested bounded-complexity and recovery constraints.

### Alternative 3 — Durable fair rounds with one reusable state row per Tenant

A singleton `scheduler_coordination` row names the current generation and priority. A short refill transaction creates or refreshes one `PENDING` `tenant_scheduler_states` row for every Tenant that has eligible work at the highest priority. Each claim transaction locks one different pending Tenant state and one Job, then atomically writes the existing Job/Attempt/Audit/Outbox changes and changes that Tenant state to `CONSUMED` (or `EMPTY`). A new generation cannot open while any current-generation state is still observably `PENDING`.

- F1: the refill linearization point selects only the highest eligible priority. A bounded active round is a snapshot admission unit; fairness never chooses a lower class within that unit.
- F2: A and B each receive exactly one state row in generation G. Until B commits `PENDING -> CONSUMED`, PostgreSQL MVCC still exposes B as pending to the refill transaction, so generation G+1—and therefore A2—cannot exist. At most A1 can precede B's first committed receipt.
- F3: every eligible same-priority Tenant receives exactly one place in the finite round; a hot Tenant cannot accumulate multiple places.
- F4/F6: the existing `EvaluationJob FOR UPDATE SKIP LOCKED` and atomic fencing transaction remain intact.
- F5: a nonblocking permit miss falls back to a blocking selection of a current pending row; after wake-up it rechecks eligibility/round state rather than returning indefinite false empty.
- F7: refill rollback creates no round; claim rollback restores both pending state and Job; a crash after refill leaves a durable pending row; no scheduler lease or in-memory owner exists.
- F8: the singleton is locked only for refill and a very short tail claim-sequence assignment. It is never held across the full claim write set or Worker execution. Claim transactions hold only their per-Tenant scheduler row plus the existing Job/Run-related locks.
- SQL/locks: one conditional refill transaction per round, then one claim transaction per admitted Tenant. With N eligible Tenants, N claim transactions proceed on different state rows. A single Tenant deliberately has one short claim transaction per round, while Target/Evaluator work remains parallel after receipt.
- hot rows: the singleton is touched once per generation and at a tail-only sequence linearization point; Tenant business rows are no longer scheduler locks.
- schema/rollback/GC: two bounded tables/rows of state—one singleton and at most one row per Tenant. Rows are reused, so no permit garbage collector is needed. Downgrade removes Candidate 3 state and leaves the earlier Tenant timestamp available for code rollback.
- observability: state generation/status and `JobAttempt.scheduler_claim_sequence` allow current-round and database-linearized diagnostics without changing the frozen application receipt gate.
- benchmark cost: extra refill work is measurable and must pass the unchanged targeted/capacity/formal gates. Failure stops Candidate 3; it does not authorize tuning or Candidate 4.

Decision: **selected as the one and only Candidate 3**.

## PostgreSQL proof sketch for the RED schedule

Assume A and B are both members of generation G.

1. A's claim locks state `(A,G)`; B's claim locks `(B,G)`. Neither blocks the other.
2. B is delayed. Its transaction has not committed, so other READ COMMITTED transactions see the prior durable value `(B,G,PENDING)`.
3. A commits `(A,G,CONSUMED)`. A later refill transaction locks only the singleton, queries current-generation pending rows and still sees B pending.
4. Because a pending member exists, refill cannot create G+1. No `(A,G+1,PENDING)` state exists, so A2 cannot enter a durable claim transaction.
5. B commits its Job and `(B,G,CONSUMED)` atomically. Only now can a refill create G+1.

Thus the Candidate 2 edge `B reservation commit -> A2 durable commit -> B durable commit` is removed. The round barrier creates `B terminal scheduler state -> next A admission`.

## Linearization points

- round membership and priority: commit of the singleton-locked refill transaction;
- permit ownership: successful `FOR UPDATE [SKIP LOCKED]` of one current-generation `PENDING` Tenant state;
- durable claim: commit of Job/Attempt/Audit/Outbox and `PENDING -> CONSUMED` in one transaction;
- database diagnostic order: increment of `scheduler_coordination.durable_claim_sequence` under a tail-only row lock immediately before commit;
- frozen receipt: unchanged application timestamp immediately after `claim()` returns.

The database sequence does not redefine release fairness. It diagnoses durable transaction order alongside the old receipt order.

## Explicit limitations to test rather than hide

- A priority that becomes eligible after a round's refill waits for the bounded active round; F1 linearizes at refill. Static-priority regression tests and frozen workloads seed Jobs before the first wave.
- A single-Tenant scheduler-only workload intentionally serializes short claim transactions by round. Evaluation work remains parallel, but the absolute overhead and 4-to-8 ratio must be measured.
- A process crash after database commit but before its caller observes the receipt can lose that process-local observation, not the Job claim. Existing lease/reaper semantics recover the running Job. The frozen no-crash fairness gate remains application receipt order.
