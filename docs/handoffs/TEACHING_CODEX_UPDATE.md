# AI EvalOps Platform — Teaching Codex Update

> **Authoritative entry changed again on 2026-08-20:** read
> [`TEACHING_CODEX_HANDOFF.md`](TEACHING_CODEX_HANDOFF.md) first. It now contains the current 21-module orchestration,
> concurrency and Agent Evaluation Infrastructure curriculum. This file is retained as a 2026-08-10 scheduler snapshot.

Current branch: `codex/final-evidence-hardening-v1`. Current required reading also includes
[`AGENT_EVALOPS_TUTORIAL.md`](../learning/AGENT_EVALOPS_TUTORIAL.md),
[`FINAL_HARDENING_REPORT.md`](../final_hardening/FINAL_HARDENING_REPORT.md) and
[`AGENT_EVAL_RESUME_EVIDENCE.md`](../resume/AGENT_EVAL_RESUME_EVIDENCE.md).

Updated: 2026-08-10<br>
Branch: `codex/evidence-gate-1`<br>
Scheduler source: `02f5e680e71d05c76c145da6895122a2cf04ba14`<br>
Qualification source: `91acdba9f5b5f1a84fb03640382c9e4871364afe`<br>
Evidence commit: `15bab58150385c9a39778d64a3e4163c10892ecc`<br>
Release: `NOT_READY_TARGETED_NEGATIVE_SCALING`

## Required teaching narrative

1. Candidate 2 fair reservation did not imply fair durable application receipt.
2. Real PostgreSQL Barrier/Event RED forced an early B reservation to receipt position 8.
3. Candidate 3 introduced durable fair rounds, singleton generation/sequence and reusable per-Tenant state.
4. Ordinary correctness passed priority, concurrency, crash, progress, deadlock and fencing obligations.
5. Historical targeted run `31327388006` completed one correctness-clean repetition but failed because schema v1
   confused Tenant-member and Job cardinalities.
6. The next stage preregistered schema v2 before implementation, wrote RED negatives and preserved the old bundle.
7. Adversarial review added boolean-version and arm-metadata-spoofing protections instead of trusting producer data.
8. New targeted run `31352270523` completed four verified rep bundles, 64 arms and 6,400 terminal Jobs; every 20:1
   vector was `2/2/2/2`.
9. Completing the evidence chain exposed the real performance result: three distributions failed the 0.95
   four-to-eight Worker scaling floor.
10. The team kept orthogonal gates separate and followed `targeted fail -> STOP` without Candidate 4 or tuning.

## Source map

- fairness invariant/state machine: `docs/release/v0.1.0/fairness_redesign/01_FAIRNESS_INVARIANT.md` through
  `05_RED_GREEN.md`;
- evidence schema reasoning: `docs/release/v0.1.0/evidence_contract_v2/`;
- current targeted decision: `evidence_contract_v2/03_REMOTE_TARGETED_DECISION.md` and
  `fairness_redesign/06_TARGETED.md`;
- immutable current evidence: `docs/results/release/v0.1.0/targeted-gh-31352270523-1/`;
- immutable old failure: `docs/results/release/v0.1.0/targeted-gh-31327388006-1/`;
- code: `app/jobs/claiming.py`, `scripts/release_evidence.py`, `scripts/run_fair_capacity_test.py`;
- tests: `tests/concurrency/test_tenant_durable_fairness.py`,
  `tests/unit/scripts/test_release_evidence.py`.

## Teaching red lines

- Do not say the current blocker is still EXPLAIN cardinality; schema v2 closed it.
- Do not call Candidate 3 universally fair; the pass is for the frozen workload.
- Do not hide the negative scaling result behind correctness/fairness success.
- Do not promote historical capacity/fault/formal values to current.
- Do not describe the workflow FAILURE as infrastructure failure; all four repetitions and evidence preservation
  succeeded, while the assessment intentionally returned nonzero.
