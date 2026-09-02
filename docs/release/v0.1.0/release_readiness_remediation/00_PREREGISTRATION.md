# Release Readiness Remediation — preregistration

Registered: 2026-09-02 (Asia/Shanghai)

## Plain-language goal

AI EvalOps is the backend that receives evaluation cases, turns them into durable asynchronous
Jobs, records each Agent/RAG attempt, and keeps enough identity and audit evidence to compare two
exact implementations honestly. This stage does not add another product feature. It tries to
answer two release questions that the current portfolio cannot answer:

1. Does a frozen RAG/Agent candidate preserve or improve answer quality on a real common case set?
2. Can the fair scheduler move from four to eight Workers without violating correctness, fairness,
   or the frozen 0.95 throughput-ratio floor?

Passing one question cannot compensate for failing the other.

## Immutable prior decisions

- Starting EvalOps source: `aea8044061e678fb8e0d5312222987c5499ea83d`.
- Portfolio: `READY_WITH_EXPLICIT_LIMITS`.
- Release: `NOT_READY_NEGATIVE_SCALING_AND_QUALITY_INPUT_BLOCKED`.
- Production: `NOT_VERIFIED`.
- Historical scheduler evidence and observer failures remain immutable. New evidence must use a new
  execution identity and must not overwrite prior bundles.
- The 0.95 scaling floor, q1000/sample100/batch1 workload, four distributions, Worker counts and
  four repetitions may not be relaxed after results are visible.

## Formal quality qualification cohort

The intended source is the pinned EnterpriseRAG-Bench release already qualified in the RAG
repository. The qualification cohort contains exactly 120 cases selected without reading model
outputs: the lexicographically first 20 question IDs from each normalized category below:

- `basic`
- `semantic`
- `completeness`
- `conflicting_information`
- `high_level`
- `information_not_found`

The dataset adapter, manifest digest, baseline SHA and candidate SHA are still `INPUT_REQUIRED`.
They become immutable in a separate source-lock commit before either arm runs. The dirty RAG working
tree must not be used; only a committed exact SHA with successful CI is eligible.

The checked-in policy is
[`benchmarks/formal_agent_quality_v1/policy.json`](../../../../benchmarks/formal_agent_quality_v1/policy.json).
It requires an exact 120-case common set and 20 cases in every category. Candidate-minus-baseline
paired bootstrap intervals use 10,000 resamples and seed `20260902`.

### Frozen automated rules

- task-success 95% CI lower bound must be at least `0.0`;
- citation-correctness 95% CI lower bound must be at least `-0.02`;
- tool-error-rate 95% CI upper bound must be at most `0.02`;
- candidate p95 latency increase must be at most 25%;
- candidate mean cost increase must be at most 25%;
- trace correlation and the required failure matrix must pass.

These rules establish controlled non-regression with bounded operational cost. A PASS is not a
universal quality-improvement claim and the public benchmark is not described as blind or hidden.

## Human review

Automated PASS can only advance the Shadow decision to `HUMAN_REVIEW_PENDING`. Exactly two distinct
people must score both hidden answers for the frozen cases. Baseline/candidate mapping is stored in
a separate restricted file. Completion requires exact coverage, no duplicate rows, agreement,
Cohen's kappa and adjudication of disagreements. Tests using fictional reviewer IDs are mechanism
tests only.

## Performance feedback loop

The local machine has Python 3.12 but no Docker or `psql`; it cannot reproduce the PostgreSQL
performance symptom. Historical synchronous and passive observers already failed the unchanged
claim-p95 perturbation budget and remain retired. This stage will not create Observer v4 or try to
reinterpret those results.

The new authorization permits exactly one minimal scheduler candidate. Its hypothesis is that the
current Claim path pays an avoidable `pending permit exists?` PostgreSQL transaction before every
successful permit transaction. If that extra round trip is material, changing the common path to
try the already-created permit first should reduce connection/transaction pressure at w8 without
changing durable fair-turn state, SQL ordering, workload identity or release thresholds.

The candidate feedback loop is:

1. add deterministic unit tests proving that an available permit does not call round creation, and
   that a missing permit still creates/rechecks a round;
2. run the existing real-PostgreSQL concurrency, correctness and fairness suites in ordinary CI;
3. run the existing uninstrumented q1000/sample100/batch1 matrix for four exact repetitions on the
   candidate source;
4. assess with the unchanged `scripts.targeted_scheduler_evidence` contract;
5. upload evidence as an immutable workflow Artifact without automatically committing it.

The candidate changes control flow only. It may not change schema, SQL ordering, Worker levels,
queue/sample/batch sizes, fairness policy, retry/backoff, lease settings, repetitions or the 0.95
floor. `VERIFIED` requires all correctness fields to remain zero, frozen fairness tests to pass and
all four w8/w4 ratios to meet the floor. Failure stops scheduler work; no threshold relaxation,
second candidate or post-result tuning is authorized in this stage.

## Promotion boundary

This stage may produce `RELEASE_CANDIDATE_ELIGIBLE` only after formal quality, real human review,
targeted correctness/fairness and all four scaling ratios pass on exact sources. It cannot claim
production readiness, a security certification, a production SLO or create a v0.1.0 Release before
the independent release decision is updated.
