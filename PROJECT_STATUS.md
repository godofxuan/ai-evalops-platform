# AI EvalOps Platform — Current Portfolio and Release Status

## Usable evaluation product candidate — 2026-09-02

- Branch: `codex/usable-eval-product-v1`.
- Clean starting point: `origin/main@aea8044061e678fb8e0d5312222987c5499ea83d`.
- Product implementation: `41de043f40c02c0d1349332c6bd19e9116202838`.
- Exact implementation CI: GitHub Actions [`33589528112`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33589528112), successful.
- Default `main`: non-force fast-forwarded from `aea8044061e678fb8e0d5312222987c5499ea83d`
  to the same implementation SHA; exact-main CI [`33590045034`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33590045034)
  completed successfully for that exact SHA.
- Product evidence commit `a57254b08c45c03d82cf60490aa48ca5d2a50670` also passed exact-main
  CI [`33590971293`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33590971293).
- Product demo: 120 paired deterministic cases, six required categories × 20, exact dataset
  SHA `563a5063ae06efcd8b4a49729bf3621887b9876ffe34bc66bf41c0b6b2bb916c`.
- Demo result: `DEMO_PASS`; statistical calculations pass, but the evidence decision is
  `INPUT_BLOCKED` with `formal_ab_eligible=false`.
- Formal RAG state: exact baseline/candidate serving inputs and a frozen unconsumed quality
  dataset are still `INPUT_REQUIRED`; two-person human review is `PENDING`.
- Historical release blocker remains `NEGATIVE_SCALING`; this product work does not change or
  rerun the frozen scaling experiment.
- Production state remains `PRODUCTION_NOT_VERIFIED`.
- Current external RAG main was re-audited at
  `bd71cb3ca8de4e1899a4ea0e09d3c1c677c77a7e`; exact CI
  [`33588082333`](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/33588082333)
  passed all four jobs. Its R5 public aggregate artifact was byte-verified at SHA-256
  `97aa582d996194171004964acfbda46732f685998dd3227b3730a8b778c404ce`.
- EvalOps can now import and validate that aggregate as `AGGREGATE_EVIDENCE_VERIFIED`, while
  remaining fail-closed at `FORMAL_CASE_RESULTS=INPUT_REQUIRED`; no 192-row `CaseResult` set was
  present or fabricated. Implementation `5f6aa5a996062d4423b94aa4f7c2a15c38fd41b3` passed
  exact-main CI [`33592493933`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33592493933).

This layer adds a strict experiment spec, code-registered evaluator plugins, SSRF-hardened HTTP
provider, paired automatic quality/citation/tool-error/latency/cost analysis, portable HTML
case drill-down, and a separately verifiable result manifest. The deterministic demo is a
usability and mechanism proof, not evidence that the real RAG improved.

## Historical Final Pair closeout snapshot — 2026-09-01

- Branch: default `main`.
- Base/start SHA: `c323d56906a30b654d59fc7c847a0efffab0a452`.
- RAG producer SHA: `2065e571d77439babf76a763ac459a618950f218`; exact CI [32555135411](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/32555135411) succeeded.
- EvalOps implementation SHA: `4040fa1db7cee6c8380ff8580fa21be17464435b`; exact CI [32558950596](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32558950596) succeeded.
- Default-main evidence baseline: `1c2f9d93b488cacf7d5f7c953c8cce906e0f9be6`; exact `main` CI [33494481676](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33494481676) succeeded.
- Migration head: `20260822_0027`.
- Final Pair Contract: `FINAL_PAIR_CONTRACT_VERIFIED`, 18 deterministic mechanism cases, 15 source/converted events, 0 dropped, 0 unmapped.
- State: `IMPLEMENTATION_COMPLETE`, `EXACT_SHA_CI_REQUIRED` satisfied for the implementation SHA, `FINAL_PAIR_CONTRACT_REQUIRED` satisfied, `MERGED_TO_DEFAULT_MAIN`, `EXACT_MAIN_SHA_CI_VERIFIED`, `NOT_RELEASED`, `PORTFOLIO_READY`.
- Evidence limits: `FORMAL_AB_NOT_RUN`, `HUMAN_REVIEW_PENDING`, `SHADOW_RELEASE_NOT_PASSED`, `PRODUCTION_NOT_VERIFIED`.

## Executable scorecard update — 2026-09-01

- Machine source: [`docs/review/PROJECT_SCORECARD.json`](docs/review/PROJECT_SCORECARD.json).
- Scorecard implementation: `0e66aed4d40ee33d3488605d536e6aaa4a299e78`; exact CI
  [`33492703967`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33492703967)
  passed both `quality-and-integration` and `compose-smoke`.
- Verifier: `python -m scripts.project_scorecard`; CI runs it after evidence-manifest verification.
- Engineering correctness and controlled reliability: `VERIFIED_CONTROLLED`.
- Agent/RAG quality and evidence sufficiency: `QUALITY_EVIDENCE_INSUFFICIENT` because no
  formal A/B or completed human review exists.
- Performance: `NEGATIVE_SCALING`; one of four frozen 4→8 workloads passed the 0.95 floor.
- Security: `EXTERNAL_VALIDATION_REQUIRED`; mechanism tests do not replace an independent
  assessment or production role-isolation proof.
- Audit operations now expose end-to-end `mcp_audit_delivery_latency_seconds` alongside
  pending age, delivery failures and dead letters, enabling a future p95/p99 SLO.

The frozen evidence replay found contention/lock-pressure associations but no qualified causal
root cause. See [`SCALABILITY_DIAGNOSIS.md`](docs/review/SCALABILITY_DIAGNOSIS.md).

The final evidence commit and its own exact CI are an append-only second-stage attestation. Until that CI succeeds, this branch must not be described as fully closed. The cross-repository contract verifies interoperability/mechanisms only; it does not demonstrate answer-quality improvement or production capacity.

## What this closeout adds

1. A versioned outer Harness Envelope digest and verified projections for answer, citations, terminal state, policy, errors and tools.
2. A `FormalEvidenceDecision` that binds dataset/case/source identities and prevents callers from supplying a naked automated `PASS`.
3. An independent system-identity Audit Dispatcher with leased `SKIP LOCKED` claims, bounded exponential retry, dead letter, idempotent sink identity and revoked-key-safe delivery.
4. An exact RAG/EvalOps Final Pair suite and machine-readable file/digest evidence.

## Historical evidence below

Everything below this heading is retained as historical context. Its former branch names, SHAs, test totals and release wording are not the current snapshot above.

## Current canonical state — 2026-08-20

- Current branch: `codex/final-evidence-hardening-v1`.
- Documentation sync PRE_SYNC_HEAD: `0b7c1a340a0dc362ff1af6948664e3a95ac06f19`.
- Final-hardening implementation baseline: `22fda896a1b24b0cf41cd1402ead521f74758ac6`.
- Migration head: `20260820_0025` (single Alembic head, verified from the revision chain).
- Portfolio state: `PORTFOLIO_READY_WITH_EXPLICIT_LIMITS`.
- Release state: `NOT_READY_TARGETED_NEGATIVE_SCALING`; no v0.1.0 tag or GitHub Release.
- Production readiness: `NOT_VERIFIED`; controlled tests and CI do not establish capacity, SLOs or a production
  security boundary.

```text
portfolio-ready != release-ready != production-ready
```

### What is current

The project now combines two evidence layers without allowing either to overwrite the other:

1. **Durable evaluation orchestration:** immutable Dataset Versions; Run → Job → lease-bound Attempt → CaseResult;
   heartbeat, owner/version/expiry/Attempt fencing; stale result/failure rejection; Reaper recovery; PostgreSQL
   `SKIP LOCKED` false-empty repair; and durable fair-turn state.
2. **Agent Evaluation Infrastructure:** framework-neutral trajectory artifacts; canonical JSON/SHA-256 identity;
   immutable ingestion; seven deterministic trajectory metric extractors with `reported`/`derived` provenance;
   common-case-only regression with explicit case-set, coverage and sufficiency fail-closed rules; source/artifact/packet
   hash-bound review with staged evaluator visibility; per-call MCP stdio credential revalidation; Agent evidence RLS
   and composite ownership foreign keys; and dry-run-first orphan-object reconciliation.

### Current CI evidence

- Final implementation run
  [`32282462281`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32282462281) passed at source
  `22fda896a1b24b0cf41cd1402ead521f74758ac6`.
- Documentation-head run
  [`32341372636`](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32341372636) passed at source
  `0b7c1a340a0dc362ff1af6948664e3a95ac06f19`.
- The current gate covers lock/format/Ruff/mypy, 826 non-integration tests, deterministic adapter evidence,
  PostgreSQL/Redis/MinIO/MCP/concurrency integrations, RLS, reconciliation, migration downgrade/re-upgrade, image build
  and Compose smoke. This is one CI topology, not production-scale evidence.

### Historical scheduler result that remains binding for release

- Bounded correctness passed in the frozen schema-v2 experiment: 64 arms and 6,400 submitted/unique/terminal Jobs,
  with protected correctness counters zero.
- Exact-workload fairness passed only for the frozen 20:1 q1000/sample100/batch1 protocol: the secondary durable
  receipt position was 2 for w1/w2/w4/w8 in all four repetitions, versus historical legacy position 953.
- Formal 4→8 scaling remains `NEGATIVE_SCALING`: single `0.782511`, balanced `0.772797`, 20:1 `0.796214`, and
  many-small `1.014063`, against a frozen 0.95 minimum for every workload.
- Measurement validity remains failed: two synchronous observers and passive PostgreSQL telemetry exceeded the frozen
  absolute claim-p95 perturbation budget. H1/H2/H3 were not run and remain inconclusive; no root cause is claimed.
- Scheduler and measurement candidate budgets remain zero. This sync does not retune or rerun frozen experiments.

### Boundaries not closed

- Execution is at-least-once; external Target/tool side effects may repeat.
- Current Agent metrics are producer-reported or trajectory-derived; none is authority-verified.
- PostgreSQL and S3/MinIO do not share an atomic commit; reconciliation reduces orphan risk but is not two-phase commit.
- Compose still shares migration/runtime database credentials, so complete production RLS role isolation is absent.
- MCP is local stdio only; no Streamable HTTP, OAuth resource server or remote MCP rate limiter exists.
- The adapter evidence is fixed fixture replay, not a live LangGraph runtime or performance benchmark.
- No production capacity, linear-scaling, SLO, on-call or security-certification claim is supported.

### Authoritative current reading order

1. [Project status](PROJECT_STATUS.md)
2. [Project evidence map](docs/handoffs/PROJECT_EVIDENCE_MAP.md)
3. [Final hardening report](docs/final_hardening/FINAL_HARDENING_REPORT.md)
4. [Agent EvalOps tutorial](docs/learning/AGENT_EVALOPS_TUTORIAL.md)
5. [Agent resume evidence](docs/resume/AGENT_EVAL_RESUME_EVIDENCE.md)
6. [Resume metric ledger](docs/handoffs/RESUME_METRIC_LEDGER.md)
7. [Interview story bank](docs/handoffs/INTERVIEW_STORY_BANK.md)
8. [Final portfolio synchronization report](docs/handoffs/FINAL_PORTFOLIO_SYNC_REPORT_20260820.md)
9. [Third-party provenance review](docs/handoffs/THIRD_PARTY_PROVENANCE.md)

## Historical scheduler/archive baseline — revalidated 2026-08-11

The remainder of this file preserves the scheduler-only archive state. Its branch, SHA, test totals and workflow IDs
are historical evidence, not the current portfolio branch.

Archive baseline: `39f381e8369e044392fbad39c3fbc75d5bdeb942`

Historical branch: `codex/evidence-gate-1`

Pull Request: [#1](https://github.com/godofxuan/ai-evalops-platform/pull/1)

## Canonical state

| Dimension | State | Exact boundary |
| --- | --- | --- |
| Bounded correctness | `PASS` | Frozen schema-v2 targeted run `31352270523`: 64 arms, 6,400 submitted/unique/terminal Jobs; protected correctness counters are zero. |
| Frozen fairness | `PASS_FOR_EXACT_WORKLOAD` | 20:1 workload only; w1/w2/w4/w8 secondary durable receipt position is 2 in every one of four repetitions. |
| Evidence contract | `VERIFIED_SCHEMA_V2` | Assessor independently checks raw PostgreSQL EXPLAIN, arm/workload identity, numeric domains, protected counters, source SHA and manifest. |
| Formal scaling | `NEGATIVE_SCALING` | 4→8 ratios: single 0.782511, balanced 0.772797, 20:1 0.796214, many-small 1.014063; frozen minimum is 0.95 for every workload. |
| Performance attribution | `STOPPED_BY_MEASUREMENT_VALIDITY` | Two synchronous observers exceeded the 10% absolute claim-p95 perturbation budget; passive PostgreSQL telemetry also exceeded it. |
| H1 / H2 / H3 | `NOT_RUN / INCONCLUSIVE` | Formal causal repetitions were not authorized after measurement qualification failed. No root cause is claimed. |
| v0.1.0 | `NOT_READY_TARGETED_NEGATIVE_SCALING` | No tag and no GitHub Release. |
| Pull Request | `Draft` | Do not merge as a v0.1.0 release candidate. |
| Production readiness | `NOT_VERIFIED` | Results are CI/controlled-experiment evidence, not production capacity, SLO or security certification. |
| Scheduler candidate budget | `0` | No Candidate 4 and no further scheduler tuning in this archive stage. |
| Measurement candidate budget | `0` | No observer v4, sampling sweep or attribution restart in this archive stage. |

## Why this is portfolio-ready while the release is not

The project demonstrates a nontrivial asynchronous backend, explicit concurrency invariants, deterministic race
reproduction, fencing, evidence contracts and release gating. The same evidence also says the frozen performance contract
failed. Preserving both facts is the engineering result:

```text
portfolio usable != release ready
```

## Verified evidence identity

- Targeted scheduler bundle: workflow `31352270523`, source `91acdba9f5b5f1a84fb03640382c9e4871364afe`.
- Targeted root manifest: 598/598 files rehashed on 2026-08-11; 0 missing, 0 size mismatches, 0 SHA-256 mismatches.
- Passive measurement qualification: workflow `31421039618`, source `aa8b29c0a90305b2898daecc34ad23d103956ba0`, measurement code `0915c10d9176191f4f306590f029ed66809cf161`.
- Passive measurement root manifest: 151/151 files rehashed on 2026-08-11; 0 missing, 0 size mismatches, 0 SHA-256 mismatches.
- Historical fault matrix: scenarios A–I, before/after summaries total 54/54 successful repetitions and zero recorded correctness violations. It is `VERIFIED_HISTORICAL`, not Candidate 3 capacity evidence.

## Preserved negative evidence

- Historical schema-v1 targeted bundle remains `FAILED`.
- Current formal scaling remains `NEGATIVE_SCALING`.
- Synchronous observer v1 and low-overhead v2 remain `INSTRUMENTATION_TOO_INTRUSIVE`.
- Passive PostgreSQL telemetry remains `MEASUREMENT_SYSTEM_INVALID`.
- Performance attribution remains `PERFORMANCE_ATTRIBUTION_STOPPED_BY_MEASUREMENT_VALIDITY`.

## Authoritative reading order

1. [Release decision](docs/release/v0.1.0/RELEASE_DECISION.md)
2. [Project evidence map](docs/handoffs/PROJECT_EVIDENCE_MAP.md)
3. [Teaching Codex handoff](docs/handoffs/TEACHING_CODEX_HANDOFF.md)
4. [Resume Codex handoff](docs/handoffs/RESUME_CODEX_HANDOFF.md)
5. [Metric ledger](docs/handoffs/RESUME_METRIC_LEDGER.md)
