# Final scheduler release decision

Date: 2026-08-09

## Decision: NOT_READY

Current and only v0.1.0 blocker: the final Candidate 2 scheduler failed the frozen concurrent 20:1 fairness contract.
At 8 workers the secondary Tenant's first durable claim completed at position 4; the required maximum is position 2.

## Six independent states

| State | Result | Evidence boundary |
|---|---|---|
| `WORKFLOW_EXECUTED` | PASS | targeted attempts `31318923861` and `31319556885` executed and preserved artifacts |
| `TESTS_PASS` | PASS | Candidate 2 and Run-lock fix passed push/PR CI |
| `CORRECTNESS_PASS` | PASS for state/fencing/uniqueness | 1,200/1,200 completed targeted Jobs; no lost/duplicate/orphan |
| `EVIDENCE_COMPLETE` | FAIL for release | targeted stopped in repetition 1; downstream current evidence intentionally not run |
| `PERFORMANCE_PASS` | NOT ESTABLISHED | four-repetition targeted and formal protocols incomplete |
| `RELEASE_READY` | NO | frozen 20:1 fairness gate failed |

## What was resolved

- The six-hour CI hang was a test-harness wait cycle caused by an external long `Tenant FOR UPDATE` blocking a durable
  claim's FK `KEY SHARE`; selector-only did not require the Tenant lock.
- `FOR NO KEY UPDATE` was proven sufficient for same-row fair-turn writer exclusion and compatible with FK readers.
- The incorrect external-lock contract was split into selector, bounded production overlap and fail-fast PostgreSQL
  semantic diagnostics.
- Candidate 2 eliminated false-empty returns in 20 repeated 10W/100J drains.
- A targeted worker RED found and fixed an independent Run-first/Job-first deadlock by using a key-preserving Run
  guard; the fix passed both real-PostgreSQL CI entry points and did not recur in 1,200 subsequent Jobs.

## Stop rule

Candidate 2 is the second and final allowed scheduler production iteration. The fairness gate is not relaxed and no
Candidate 3 is attempted. Capacity, same-runner paired, current A-I fault and formal 32-arm workflows remain
`NOT_RUN`. PR #1 stays Draft; there is no merge, tag or GitHub Release.

The project should stop scheduler development for this sprint. The next phase after v0.1.0 re-planning should be one
focused scheduler redesign proposal with an explicit concurrent fairness invariant before any additional code.
