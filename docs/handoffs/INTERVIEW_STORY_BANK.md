# AI EvalOps Platform — Interview Story Bank

Updated: 2026-08-20 on `codex/final-evidence-hardening-v1`. Use these as evidence-backed outlines, not memorized scripts. Start with the decision/result, then show
the mechanism. Never remove limitations or turn historical evidence into current production claims.

Stories 1–10 preserve orchestration/scheduler/release history; stories 11–15 cover current final-hardening Agent Evaluation
Infrastructure. The latter can defend `CURRENT_POSITIVE_RESUME` bullets. Negative performance/measurement results remain
`HISTORICAL_NEGATIVE` and belong in interviews or limitations, not the default resume summary.

## Story 1 — Making retries auditable with Job and Attempt

- **Problem:** one evaluation case may retry after process failure, but the platform must retain durable intent and execution history.
- **Risk:** collapsing intent and execution overwrites history and lets stale executions look current.
- **Hypothesis:** separate Job from lease-bound Attempt and guard every transition in PostgreSQL.
- **Implementation:** Run creates case Jobs; claim atomically creates Attempt and writes owner/version/expiry; terminal paths close Attempt and Job together.
- **Experiment:** real PostgreSQL concurrent claim/recovery tests plus the 64-arm targeted run.
- **Evidence:** 6,400 submitted = 6,400 unique = 6,400 terminal; orphan and Attempt-sequence mismatch counters are 0.
- **Decision:** retain explicit state-machine entities and describe execution as at-least-once.
- **Limitation:** bounded CI evidence; external Target effects are not transactionally exactly-once.
- **What I learned:** retry safety starts with modeling authority and history, not retry-loop syntax.

## Story 2 — Fencing a stale Worker

- **Problem:** Worker A can resume after its lease expired and Worker B reclaimed the Job.
- **Risk:** A’s late result/failure overwrites B’s valid outcome.
- **Hypothesis:** require owner, lease version, live expiry and active Attempt on every durable commit.
- **Implementation:** conditional heartbeat/result/failure statements, row locks and unique CaseResult persistence.
- **Experiment:** stale heartbeat/result/failure races and historical fault scenarios C/D.
- **Evidence:** current targeted stale success/failure accepted = 0; historical matrix also records 0.
- **Decision:** use version/Attempt fencing; do not treat `worker_id` as a fencing token.
- **Limitation:** cannot undo an arbitrary external side effect already performed by the stale Worker.
- **What I learned:** ownership identity and ownership generation solve different problems.

## Story 3 — Competing Reapers without double recovery

- **Problem:** expired RUNNING Jobs must recover with several Reapers.
- **Risk:** double retry, inconsistent Attempt closure, or partial state after a Reaper crash.
- **Hypothesis:** lock expired Jobs with `FOR UPDATE SKIP LOCKED` and recover atomically.
- **Implementation:** ordered expiry scan, Attempt closure and retry/fail/cancel in one transaction.
- **Experiment:** dual-Reaper concurrency test and historical scenario H.
- **Evidence:** historical A–I before/after summaries total 54/54 successes and 0 recorded violations.
- **Decision:** keep database-coordinated competing consumers and at-least-once semantics.
- **Limitation:** historical matrix is not current capacity, deadlock-freedom or availability-SLO evidence.
- **What I learned:** `SKIP LOCKED` divides immediate work but does not prove fairness.

## Story 4 — Durable fairness under 20:1 tenant skew

- **Problem:** legacy FIFO lets a heavy tenant occupy the first 952 receipts.
- **Risk:** a small tenant has extreme queue position despite eligible work.
- **Hypothesis:** persist fair rounds and tenant permits so concurrent Workers share one durable order.
- **Implementation:** coordination generation/sequence, tenant permit states and exact-priority atomic permit+Job claim.
- **Experiment:** frozen q1000/sample_jobs=100/batch=1, 20:1 workload at w1/w2/w4/w8, four repetitions.
- **Evidence:** fair secondary position is 2 in every observation; legacy is 953.
- **Decision:** Candidate 3 passes the exact frozen fairness contract.
- **Limitation:** not universal/strong fairness, starvation-free or arbitrary-workload proof.
- **What I learned:** a strong metric must include workload identity and receipt definition.

## Story 5 — Deterministic `SKIP LOCKED` false-empty RED→GREEN

- **Problem:** the only eligible Job could be locked while another transaction held the tenant permit.
- **Risk:** `SKIP LOCKED` returned empty and old code persisted permit `EMPTY`, losing a valid turn.
- **Hypothesis:** empty visibility is not absence; separately probe eligibility before consuming the permit.
- **Implementation:** no-row claim triggers non-locking exists; keep `PENDING` if work exists and use waiting fallback.
- **Experiment:** event-coordinated real PostgreSQL interleaving without timing sleeps.
- **Evidence:** RED `31397416017`; GREEN `31398322919` and `31398332668`.
- **Decision:** ship the narrow correctness fix and rerun qualification/targeted evidence.
- **Limitation:** an observation window remains; no universal liveness theorem is claimed.
- **What I learned:** concurrency APIs describe what was observable, not necessarily what exists.

## Story 6 — Evidence contract v2

- **Problem:** schema v1 trusted summary cardinality and producer metadata too much.
- **Risk:** stale/mislabeled arms or the wrong EXPLAIN node could appear valid.
- **Hypothesis:** bind identity and independently parse raw evidence, failing closed on ambiguity.
- **Implementation:** validate source SHA, arm/workload metadata, candidate unit, numeric domains, protected counters, raw plans and manifest.
- **Experiment:** adversarial tests mutate plan, metadata, counters, source and manifest; four current bundles qualify.
- **Evidence:** 598/598 root entries rehashed cleanly; 64 arms and 512 EXPLAIN summaries covered.
- **Decision:** preserve schema-v1 failure and use schema-v2 as current evidence.
- **Limitation:** hashes provide integrity, not signer authenticity or production representativeness.
- **What I learned:** reproducibility needs an independent consumer contract, not more producer columns.

## Story 7 — Letting negative scaling block release

- **Problem:** correctness passed, but release also required acceptable 4→8 scaling on all workloads.
- **Risk:** celebrating correctness could hide release-relevant performance failure.
- **Hypothesis:** preregister median aggregation and a 0.95 ratio floor.
- **Implementation:** source-bound assessor computes w8/w4 for every distribution and requires all to pass.
- **Experiment:** four repetitions, four distributions, w1/w2/w4/w8, 64 arms/6,400 Jobs.
- **Evidence:** ratios 0.782511, 0.772797, 0.796214, 1.014063; 3/4 failed.
- **Decision:** v0.1.0 remains `NOT_READY`; no tag, merge or Release.
- **Limitation:** controlled CI result; it neither diagnoses cause nor proves production capacity.
- **What I learned:** a release gate matters when it can reject work you invested in.

## Story 8 — Rejecting three measurement designs

- **Problem:** a trustworthy bottleneck diagnosis needed instrumentation that did not materially change the claim path.
- **Risk:** observer effect could make scheduler changes respond to the tool rather than the system.
- **Hypothesis:** qualify OFF/ON under frozen absolute throughput and claim-p95 budgets first.
- **Implementation:** synchronous v1, lower-overhead v2, then external 5 Hz PostgreSQL wait sampling with balanced order.
- **Experiment:** each ran its preregistered qualification; passive used OFF/ON/ON/OFF and ON/OFF/OFF/ON.
- **Evidence:** absolute claim-p95 changes 11.3194%, 13.4906%, 28.0396%, all above 10%; passive manifest 151/151 clean.
- **Decision:** first two `INSTRUMENTATION_TOO_INTRUSIVE`, third `MEASUREMENT_SYSTEM_INVALID`; stop attribution.
- **Limitation:** qualification failure does not explain why ON changed direction.
- **What I learned:** “passive” and “ON faster” are hypotheses, not validity guarantees.

## Story 9 — Refusing to force H1/H2/H3

- **Problem:** reservation/coordination, DB waits/locks and runner/resources were plausible explanations.
- **Risk:** plausible observations could be narrated as causal after qualification failed.
- **Hypothesis:** formal repetitions run only after measurement validity passes.
- **Implementation:** workflow hard-gated formal attribution behind qualification.
- **Experiment:** qualification ran; formal H1/H2/H3 sections were skipped by contract.
- **Evidence:** `formal_attribution = NOT_RUN`; final `PERFORMANCE_ATTRIBUTION_STOPPED_BY_MEASUREMENT_VALIDITY`.
- **Decision:** keep all hypotheses `INCONCLUSIVE` and make no root-cause claim.
- **Limitation:** the portfolio ends without a bottleneck explanation.
- **What I learned:** causal discipline is demonstrated by what you refuse to conclude.

## Story 10 — Stopping before Candidate 4

- **Problem:** after failure it was tempting to tune Workers/batch/pool/lease/threshold or invent another scheduler.
- **Risk:** post-hoc search expands researcher degrees of freedom and overfits benchmark/narrative.
- **Hypothesis:** frozen candidate budgets protect the meaning of prior evidence.
- **Implementation:** production scheduler candidate budget = 0; measurement candidate budget = 0; archive only.
- **Experiment:** no Candidate 4 or observer v4 ran; consistency checks preserve negative results.
- **Evidence:** release NOT_READY, PR Draft, H1/H2/H3 NOT_RUN/INCONCLUSIVE.
- **Decision:** close as portfolio-ready but release-not-ready.
- **Limitation:** future progress requires newly scoped authorization and preregistration.
- **What I learned:** stopping is engineering work when more activity would reduce evidentiary credibility.

## Story 11 — Making trajectory identity reproducible without calling it truth

- **Problem:** Agent frameworks emit differently shaped, mutable traces that are hard to compare later.
- **Risk:** reserialization or producer claims can silently change the evidence behind a metric.
- **Hypothesis:** normalize into one versioned envelope and hash canonical bytes before immutable ingestion.
- **Implementation:** framework-neutral trajectory schema, canonical JSON/SHA-256, immutable artifact reference and implementation/config/provenance-bound result rows.
- **Experiment:** schema/evaluator unit tests plus authenticated PostgreSQL/MinIO workflow in CI `32282462281`.
- **Evidence:** exactly seven deterministic extractor kinds persist `reported` or `derived` provenance.
- **Decision:** use content identity and deterministic extraction, but never call the metrics authority-verified.
- **Limitation:** a hash proves byte identity, not factual truth, authorship or signature authenticity.
- **What I learned:** reproducibility and epistemic authority are different axes.

## Story 12 — Failing regression closed on insufficient common evidence

- **Problem:** two runs can have different case sets or too little overlap for a defensible regression verdict.
- **Risk:** aggregate comparison can turn one favorable common case into a false PASS.
- **Hypothesis:** pin every selected evidence ID and require an explicit case policy, coverage and minimum sample count.
- **Implementation:** exact/intersection/allow-diff policies, common-case calculation, sufficiency gates and immutable comparison manifest/request SHA replay.
- **Experiment:** unit, API and real Agent workflow tests cover missing cases, low coverage, low samples and replay.
- **Evidence:** insufficient evidence becomes a fail-closed verdict rather than a silently comparable run.
- **Decision:** keep thresholds caller-defined and visible; never advertise a universal model-quality standard.
- **Limitation:** intersection improves comparability while potentially hiding behavior outside the common set.
- **What I learned:** evidence selection is part of the result and must itself be immutable.

## Story 13 — Reducing reviewer anchoring with source-bound packets

- **Problem:** reviewers can see prior evaluator/reviewer outcomes or review different source material.
- **Risk:** anchoring and source drift make adjudication difficult to audit.
- **Hypothesis:** bind packet identity to source/result/artifact hashes and stage visibility until adjudication.
- **Implementation:** immutable review source identity, packet SHA, double-review flow and evaluator-visibility policy.
- **Experiment:** review unit/API/workflow tests cover packet hashes, source binding and visibility stages.
- **Evidence:** current CI verifies that the packet and selected evidence identities remain linked.
- **Decision:** describe the workflow as auditable review, not objective or independently verified truth.
- **Limitation:** software controls cannot remove human bias or make a label universally correct.
- **What I learned:** blinding is a data-access invariant, not merely a reviewer instruction.

## Story 14 — Revoking an MCP credential between calls

- **Problem:** a long-lived stdio process can outlive the validity of its startup credential.
- **Risk:** session-only authorization allows calls after revocation or tenant disablement.
- **Hypothesis:** revalidate credential and tenant status inside every tool/resource call.
- **Implementation:** official MCP SDK v2 stdio adapter delegates through the authenticated service layer and records bounded trace/resource audit identity.
- **Experiment:** a real MCP stdio subprocess authenticates, succeeds, is revoked, then is denied on the next call.
- **Evidence:** MCP integrations passed run `32282462281`.
- **Decision:** keep the implemented claim to local stdio per-call authorization.
- **Limitation:** no Streamable HTTP, OAuth resource server or remote rate limiter exists.
- **What I learned:** transport connection lifetime is not an authorization lifetime.

## Story 15 — Reconciling non-atomic database and object-store writes

- **Problem:** PostgreSQL rows and S3/MinIO objects cannot commit in one local ACID transaction.
- **Risk:** a crash can leave an unreferenced blob, while premature cleanup can delete an in-flight object.
- **Hypothesis:** scan dry-run-first, wait through a grace window, recheck references, retry deletion and audit every action.
- **Implementation:** shared SHA-256 identity, reconciliation repository/service and durable audit events.
- **Experiment:** real PostgreSQL/MinIO tests cover dry-run, grace, recheck-before-delete, retry and audit behavior.
- **Evidence:** reconciliation integration passed run `32282462281`.
- **Decision:** use compensating cleanup and explicitly reject an atomic/two-phase-commit claim.
- **Limitation:** reconciliation is eventual risk reduction and depends on correct retention/grace policy.
- **What I learned:** an honest cross-store design starts by naming the half-commit windows.
