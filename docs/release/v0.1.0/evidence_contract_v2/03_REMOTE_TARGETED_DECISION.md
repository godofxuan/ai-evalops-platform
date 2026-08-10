# Evidence contract v2 — remote targeted decision

Date: 2026-08-10

## Decision

The schema-v2 evidence repair worked. The new four-repetition targeted run completed every workload arm and every
rep bundle independently verified. The release still remains `NOT_READY` because the complete repeated performance
gate produced `NEGATIVE_SCALING` in three of four distributions.

This is a successful evidence-contract repair followed by a genuine performance rejection. It is not another
assessor failure and it is not permission to tune parameters or start Candidate 4.

## Exact identity chain

| Item | Identity/result |
|---|---|
| evidence-contract source | `91acdba9f5b5f1a84fb03640382c9e4871364afe` |
| ordinary push CI | `31351821014`, SUCCESS |
| ordinary PR CI | `31351825433`, SUCCESS |
| targeted workflow | `31352270523`, workflow FAILURE because assessment returned nonzero |
| targeted protocol execution | four repetitions step SUCCESS |
| repeated assessment | `NEGATIVE_SCALING` |
| evidence bot commit | `15bab58150385c9a39778d64a3e4163c10892ecc` |
| artifact | `targeted-gh-31352270523-1`, 1,395,629 bytes |
| artifact digest | `sha256:6b5f68821b90ee6bdbb36d66aba0087864ca2048ac356ec3cb701e378d0c120f` |
| PR/release | PR #1 remains Draft; no merge, tag or GitHub Release |

The targeted source includes only the evidence-contract change on top of Candidate 3. No scheduler, Worker,
migration, workload, threshold or runtime parameter changed from the previously qualified correctness source.

An independent local top-level manifest audit found 598 declared and 598 actual payload files, an exact file-set
match and zero size/SHA-256 mismatches. The first audit script incorrectly excluded every nested file named
`manifest.json`, producing a false 598-versus-594 set mismatch; restricting the exclusion to the top-level manifest
itself corrected the audit. The four rep manifests are payloads of the sealed top-level bundle.

## Workflow-step interpretation

The distinction between workflow failure and protocol execution is important:

- checkout, dependency sync, Compose, migrations: SUCCESS;
- `Execute four targeted repetitions`: SUCCESS;
- diagnostics preservation: SUCCESS;
- `Assess repeated self-scaling gate and seal manifest`: FAILURE because the assessor returned
  `NEGATIVE_SCALING`;
- immutable artifact upload: SUCCESS;
- immutable evidence commit: SUCCESS;
- Compose teardown: SUCCESS.

The run therefore failed for the preregistered performance result, not because infrastructure or a repetition
crashed.

## Per-repetition evidence

Each rep bundle is manifest-bound schema 2 and was independently reassessed after download/pull:

| Repetition | Bundle status | Arms | Jobs | 20:1 positions w1/w2/w4/w8 |
|---:|---|---:|---:|---|
| 1 | VERIFIED | 16/16 | 1,600/1,600 terminal | `2/2/2/2` |
| 2 | VERIFIED | 16/16 | 1,600/1,600 terminal | `2/2/2/2` |
| 3 | VERIFIED | 16/16 | 1,600/1,600 terminal | `2/2/2/2` |
| 4 | VERIFIED | 16/16 | 1,600/1,600 terminal | `2/2/2/2` |

Across all 64 arms: 6,400 submitted, 6,400 unique terminal and zero lost, duplicate durable result,
stale-success accepted, stale-failure accepted, illegal transition, orphan nonterminal, Attempt sequence mismatch
or empty-while-eligible count.

The 512 EXPLAIN summaries have the expected selector/unit/cardinality matrix:

| Records | Selector | Unit | Cardinality |
|---:|---|---|---:|
| 64 | fair | `eligible_tenant_round_members` | 1 |
| 64 | fair | `eligible_tenant_round_members` | 4 |
| 64 | fair | `eligible_tenant_round_members` | 2 |
| 64 | fair | `eligible_tenant_round_members` | 100 |
| 256 | legacy FIFO | `eligible_jobs` | 1000 |

This closes the old `postgres_explain_candidate_cardinality_mismatch`; it is not a blocker in any new rep.

## Formal self-scaling result

The gate compares median Jobs/s at four and eight Workers and requires `w8 / w4 >= 0.95` in every distribution.

| Distribution | w4 observations Jobs/s | w4 median | w8 observations Jobs/s | w8 median | Ratio | Result |
|---|---|---:|---|---:|---:|---|
| single Tenant | 24.260244 / 24.119929 / 21.401953 / 25.325891 | 24.190086 | 16.957257 / 19.056488 / 18.813628 / 19.044379 | 18.929004 | 0.782511 | NEGATIVE_SCALING |
| balanced | 43.985512 / 45.520138 / 43.619528 / 47.623377 | 44.752825 | 34.553803 / 34.615939 / 35.863475 / 33.417059 | 34.584871 | 0.772797 | NEGATIVE_SCALING |
| 20:1 | 31.317231 / 33.917812 / 33.125251 / 32.275259 | 32.700255 | 24.723075 / 25.958697 / 26.114095 / 27.241024 | 26.036396 | 0.796214 | NEGATIVE_SCALING |
| many-small | 46.817701 / 40.825713 / 41.953877 / 42.537715 | 42.245796 | 43.625715 / 43.422944 / 41.951968 / 42.256866 | 42.839905 | 1.014063 | VERIFIED |

The negative distributions are stable across all four observations: every w8 observation is below every w4
observation for single, balanced and 20:1. This is not a median artifact.

## Diagnostic interpretation

Median w8 contention also increased in the negative distributions:

- single: retries 251 -> 460.5, retry/success 2.510 -> 4.605, claim p95 308.1 -> 1336.7 ms;
- balanced: retries 0 -> 94, retry/success 0 -> 0.940, claim p95 120.3 -> 326.4 ms;
- 20:1: retries 100.5 -> 266, retry/success 1.005 -> 2.660, claim p95 156.4 -> 599.3 ms.

This supports, but does not by itself prove, the hypothesis that concentrated-Tenant fair-round coordination and
contention dominate at eight Workers. Many-small has no median contention retries and passes throughput scaling,
although its latency still rises. A future separately authorized design stage would need a new deterministic
performance diagnosis before changing production code.

## Stop rule and resulting state

The frozen order requires targeted PASS before current capacity, same-runner, fault and formal workflows. Because
three mandatory distributions failed the 0.95 floor:

- current 1k/10k/100k capacity: `NOT_RUN_STOPPED`;
- current same-runner A/B/C: `NOT_RUN_STOPPED`;
- current A-I x3 fault: `NOT_RUN_STOPPED`;
- current formal 32-arm: `NOT_RUN_STOPPED`;
- Candidate 4, threshold relaxation and parameter gambling: not authorized;
- v0.1.0: `NOT_READY_TARGETED_NEGATIVE_SCALING`.

Historical capacity/fault/formal bundles remain historical only. The previous schema-v1 failed bundle also remains
immutable and failed; it documents why schema v2 was required.
