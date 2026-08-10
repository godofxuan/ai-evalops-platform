# Passive telemetry overhead qualification

## Outcome

`OBSERVED`: GitHub Actions workflow `31421039618` executed the preregistered sequence exactly once:

```text
Block A: OFF, ON, ON, OFF
Block B: ON, OFF, OFF, ON
```

All eight exact-arm bundles were `VERIFIED`. The measurement assessor returned:

```text
MEASUREMENT_SYSTEM_INVALID
PERFORMANCE_ATTRIBUTION_STOPPED_BY_MEASUREMENT_VALIDITY
```

The only failed validity condition was `claim_p95_perturbation_exceeded`.

## Frozen identity

| Item | Frozen value |
|---|---|
| arm | `fair-q1000-skew_20_to_1-w8-b1` |
| queue | 1,000 |
| distribution | `skew_20_to_1` |
| workers | 8 |
| claim batch | 1 |
| measured Jobs | 100 |
| telemetry | external PostgreSQL process and connection |
| views | `pg_stat_activity`, `pg_locks`, `pg_class` |
| sampling | 5 Hz |
| throughput gate | absolute relative change <= 5% |
| claim-p95 gate | absolute relative change <= 10% |
| source commit | `aa8b29c0a90305b2898daecc34ad23d103956ba0` |
| measurement code | `0915c10d9176191f4f306590f029ed66809cf161` |
| preregistration | `1c87fb218e334790812080701bd74b81488bf19c` |
| integration-fix preregistration | `2180646802d41abfb5b9fdb6abd7b203cbced1fb` |

`CODE_FACT`: The workload runner did not enable the retired synchronous performance-attribution
callback. ON differed from OFF only by the separately launched passive collector.

## Raw gated observations

| Position | Block | Mode | Rep | Jobs/s | Claim p95 ms |
|---:|:---:|:---:|---:|---:|---:|
| 1 | A | OFF | 1 | 29.937430 | 582.003366 |
| 2 | A | ON | 1 | 31.180970 | 466.961370 |
| 3 | A | ON | 2 | 29.691850 | 321.748555 |
| 4 | A | OFF | 2 | 29.900266 | 659.328240 |
| 5 | B | ON | 3 | 29.889049 | 693.985425 |
| 6 | B | OFF | 3 | 29.138523 | 758.050947 |
| 7 | B | OFF | 4 | 30.451013 | 863.944845 |
| 8 | B | ON | 4 | 29.052526 | 552.990033 |

## Independent calculation audit

The following figures were recalculated directly from the eight committed `arms.csv` files, not
copied from the assessor summary.

| Metric | Mode | Min | Max | Mean | Median | Range | Range/mean | MAD |
|---|:---:|---:|---:|---:|---:|---:|---:|---:|
| Jobs/s | OFF | 29.138523 | 30.451013 | 29.856808 | 29.918848 | 1.312490 | 0.043959 | 0.275373 |
| Jobs/s | ON | 29.052526 | 31.180970 | 29.953599 | 29.790450 | 2.128444 | 0.071058 | 0.418261 |
| Claim p95 ms | OFF | 582.003366 | 863.944845 | 715.831849 | 708.689593 | 281.941479 | 0.393866 | 88.023791 |
| Claim p95 ms | ON | 321.748555 | 693.985425 | 508.921346 | 509.975702 | 372.236871 | 0.731423 | 113.512028 |

`DERIVED`:

```text
throughput change
= (29.790449559753 - 29.918848048580) / 29.918848048580
= -0.004291558573
= -0.429156%

absolute throughput perturbation = 0.429156% <= 5%  PASS

claim-p95 change
= (509.975701550010 - 708.689593199982) / 708.689593199982
= -0.280396232083
= -28.039623%

absolute claim-p95 perturbation = 28.039623% > 10%  FAIL
```

The negative sign does not make the claim-p95 result acceptable. The preregistered test is
direction-independent because either a slowdown or a speed-up can indicate that observation changed
contention timing.

## Adjacent counterbalanced observations

| Block | Positions | Throughput change | Claim-p95 change |
|:---:|:---:|---:|---:|
| A | 1-2 | +4.153797% | -19.766552% |
| A | 3-4 | -0.697039% | -51.200550% |
| B | 5-6 | +2.575720% | -8.451348% |
| B | 7-8 | -4.592578% | -35.992438% |

`OBSERVED`: Three of four adjacent comparisons exceed the 10% claim-p95 budget in absolute terms.
The signs and magnitudes vary, which is compatible with a noisy, order-sensitive high-contention
system. This table is descriptive; it is not a significance test and does not replace the frozen
median gate.

## Correctness, isolation and integrity

`OBSERVED`: Every repetition submitted 100 Jobs, observed 100 unique Jobs and 100 terminal Jobs.
Lost Jobs, duplicate durable results, accepted stale success/failure, illegal transitions, orphan
nonterminal Jobs, attempt-sequence mismatches and `empty_while_eligible` were all zero.

`OBSERVED`: The four ON repetitions recorded 17, 17, 17 and 18 successful telemetry samples (69
total), with 16, 16, 16 and 17 samples observing waits. They wrote 5,393 projected rows. All four
reported zero telemetry errors, dropped samples and buffer overflows. Query latency maxima were
8.692, 34.370, 11.296 and 15.971 ms.

`OBSERVED`: The sealed root manifest contains 151 entries and independently matches 151 actual files,
with zero missing, extra, size-mismatched or SHA-256-mismatched files. Its SHA-256 is
`c85a88b3acf1713b2736c036b1a19ca264cb4f52e274a75e299af93cf08ffe15`; the uploaded artifact digest
is `c9c46bbe33f9581b921bbc6289814bf59270b271d276e93eaab584db81e76b35`.

`OBSERVED`: Logical fixture counts were zero before and after every repetition. PostgreSQL database
size nevertheless grew from 9,213,631 bytes before position 1 to 17,471,167 bytes after position 8.
This physical-size drift is disclosed rather than interpreted away; the counterbalanced order
reduces simple mode/order confounding but does not make an eight-run experiment drift-free.

## Qualification decision

The candidate satisfies throughput, correctness, telemetry-integrity, workload-identity, order and
manifest requirements. It fails the absolute claim-p95 gate by 18.039623 percentage points.

Therefore:

```text
MEASUREMENT_SYSTEM_INVALID
PERFORMANCE_ATTRIBUTION_STOPPED_BY_MEASUREMENT_VALIDITY
```

H1, H2 and H3 remain `NOT_RUN`. No fourth observer, extra repetition, threshold change, scheduler
candidate or formal attribution run is authorized.
