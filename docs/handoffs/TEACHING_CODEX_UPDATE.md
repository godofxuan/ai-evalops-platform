# AI EvalOps Platform — Teaching Codex Update

Updated: 2026-08-10<br>
Branch: `codex/evidence-gate-1`<br>
Candidate 3 source: `02f5e680e71d05c76c145da6895122a2cf04ba14`<br>
Evidence commit before docs closure: `90a4e03ae75d0ae391f16f32934c144430de196d`<br>
Release: `NOT_READY_TARGETED_EVIDENCE`

## Required teaching narrative

1. Candidate 2 fair reservation did not imply fair durable application receipt.
2. Real PostgreSQL Barrier/Event RED forced an early B reservation to receipt position 8.
3. F1–F8 froze priority, bounded 20:1 fairness, no starvation, uniqueness, liveness, fencing, crash safety and bounded
   coordination before Candidate 3 code.
4. Candidate 3 is the only authorized redesign: durable fair rounds, singleton generation/sequence and reusable
   per-Tenant pending/consumed/empty state.
5. Ordinary PostgreSQL CI passed deterministic fairness, 20×10W/100J, priority, crash, progress, deadlock and fencing.
6. Targeted rep1 completed 16 correctness-clean arms and observed 20:1 positions `2/2/2/2` in both application and DB
   order.
7. The formal targeted bundle still failed because Candidate 3 fair EXPLAIN counts Tenant round members while the
   assessor requires queue Jobs; 64/128 EXPLAIN summaries mismatched.
8. The team followed `targeted fail -> STOP`: no Candidate 4, assessor relaxation/retry or downstream gates.

## Source map

- invariant: `docs/release/v0.1.0/fairness_redesign/01_FAIRNESS_INVARIANT.md`
- Candidate 2 trace: `02_CANDIDATE2_OVERTAKE_TRACE.md`
- design/state machine: `03_SCHEDULER_REDESIGN_PROPOSAL.md`, `04_CANDIDATE3_STATE_MACHINE.md`
- TDD/CI: `05_RED_GREEN.md`
- targeted failure: `06_TARGETED.md`
- code: `app/jobs/claiming.py`, `app/db/models.py`, migration `20260810_0018_fair_scheduler_rounds.py`
- tests: `tests/concurrency/test_tenant_durable_fairness.py`, `tests/unit/jobs/test_fair_round_claiming.py`
- immutable evidence: `docs/results/release/v0.1.0/targeted-gh-31327388006-1/`

## How to teach PART 41–54

The main teaching handoff now contains PART 41–54. Every part has the required concept, project problem, source,
RED, experiment, failure history, final method, trade-off, interview prompt and exercises. Do not skip PART 48
(metric preregistration), PART 52 (orthogonal gates), PART 53 (source binding) or PART 54 (historical boundary); those
chapters explain why a technically promising rep1 still cannot become a release claim.

## Teaching red lines

- Never say Candidate 3 fully passed fairness or performance.
- Never replace the frozen application receipt with DB sequence after seeing failure.
- Never call the evidence-cardinality mismatch harmless and silently rerun.
- Never promote historical capacity/fault/formal to Candidate 3.
- Keep the positive teaching outcome: disciplined concurrency reasoning, deterministic RED, bounded design,
  source-bound evidence and an honest stop decision.
