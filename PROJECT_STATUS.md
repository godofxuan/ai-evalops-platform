# AI EvalOps Platform — Final Portfolio Status

Last evidence revalidation: 2026-08-11

Archive baseline: `39f381e8369e044392fbad39c3fbc75d5bdeb942`

Branch: `codex/evidence-gate-1`

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
