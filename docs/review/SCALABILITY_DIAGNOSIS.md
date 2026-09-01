# Scheduler Scalability Diagnosis — Frozen Evidence Replay

## Scope

This diagnosis replays the immutable `targeted-gh-31352270523-1` evidence. It does not
rerun the 64-arm/6,400-Job experiment and does not authorize another scheduler candidate.
The local host has no Docker/PostgreSQL runtime, so no code change can currently be tested
against the original performance symptom. Accordingly, the findings below are associations,
not a claimed root cause.

## Reproduced symptom

The manifest-bound assessment contains four repetitions for each distribution and worker
count. The 4→8 throughput floor is 0.95; three of four workloads fail.

| Distribution | Throughput 8÷4 | Claim p95 multiplier | Reservation p95 multiplier | Retry delta | Fallback delta | Lock-wait peak delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| single tenant | 0.782511 | 4.339× | 1.523× | +209.5 | +88.5 | +3.5 |
| balanced multi-tenant | 0.772797 | 2.714× | 2.557× | +94 | +59 | 0 |
| 20:1 skew | 0.796214 | 3.833× | 1.496× | +165.5 | +82 | +3 |
| many small tenants | 1.014063 | 5.599× | 8.299× | 0 | 0 | +1.5 |

The exact values are recomputed by `python -m scripts.project_scorecard` from the root
manifest, the four `arms.csv` files and `assessment.json`.

## Ranked hypotheses and disposition

1. **Hot tenant/eligible-job row contention — associated, not causally proven.** Retry and
   waiting-fallback counts rise in all three failing workloads and remain zero for the one
   throughput-passing many-small workload. Prediction for a future qualified run: spreading
   eligible work over more tenant-state rows should reduce retries and improve throughput.
2. **PostgreSQL lock/connection pressure — associated, not causally proven.** Lock-wait peaks
   rise in single and skew, but do not explain balanced by themselves. Prediction: a qualified
   PostgreSQL wait-event trace should align wait time with failed Claim transactions.
3. **Worker coordination/transaction fixed cost — unresolved.** Claim-segment latency grows
   even in many-small, while CPU and RSS remain broadly flat. Prediction: transaction/query
   spans, rather than process resource use, should dominate added w8 time.
4. **Measurement perturbation — not ruled out.** Historical observer qualification breached
   the frozen claim-p95 perturbation budget. No causal performance conclusion may use those
   observer results until a lower-perturbation measurement loop qualifies.

## Decision

- Correctness and exact-workload fairness evidence remain valid.
- `NEGATIVE_SCALING` remains binding for release.
- No scheduler code was changed because there is no qualified feedback loop capable of
  proving the original symptom disappears.
- The smallest justified next experiment is a new, separately authorized 4-vs-8 diagnostic
  with the same workload identity, four repetitions, observer qualification before use, and
  PostgreSQL wait-event/transaction spans. It must produce new evidence and must not overwrite
  the frozen result.
