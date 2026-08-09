# Concurrent fairness redesign pre-flight

Date: 2026-08-10 (Asia/Shanghai)  
Status: `VERIFIED`  
Release state at entry: `NOT_READY`

## Why this check happens before any scheduler edit

The previous audit named `138f2cb276167506abb96064c7d4239ab73a707e` as a baseline, not as a reset target. Re-reading the repository and GitHub state first prevents three evidence errors: changing the wrong source, overwriting uncommitted user work, or describing a historical failure as current.

## Repository facts

| Check | Observation | Effect on this stage |
|---|---|---|
| `git status --short` | clean | No user work needs to be moved or overwritten. |
| `git branch --show-current` | `codex/evidence-gate-1` | Work continues on the requested branch. |
| `git rev-parse HEAD` | `138f2cb276167506abb96064c7d4239ab73a707e` | The audit baseline is still current; no reset is performed. |
| `git diff` | empty | The redesign starts from a reproducible source. |
| local tags | none | No local `v0.1.0` release exists. |
| remote | `https://github.com/godofxuan/ai-evalops-platform.git` | GitHub source is the requested public repository. |
| `AGENTS.md` | absent | No additional repository-local execution policy applies. |

The latest local history begins with:

```text
138f2cb docs(release): close final scheduler qualification
f1a276f evidence(scheduler): preserve targeted run targeted-gh-31319556885-1
246252e perf(scheduler): retry targeted qualification
3350c23 fix(jobs): keep run completion locks key-preserving
511d6f1 evidence(scheduler): preserve targeted run targeted-gh-31318923861-1
```

There is no `138f2cb -> current HEAD` delta to explain.

## GitHub facts

| Surface | Current fact |
|---|---|
| PR | `#1`, open and Draft |
| PR title | `[Draft] v0.1.0 RC evidence - NOT_READY fairness gate` |
| PR head | `codex/evidence-gate-1` at `138f2cb276167506abb96064c7d4239ab73a707e` |
| PR body | Current fairness blocker is presented before separately labelled historical evidence. It is not stale. |
| latest branch push CI | run `31320691479`, success |
| latest PR CI | run `31320695526`, success |
| merge | not merged |
| GitHub tag/release | none |

The requested PR correction was already present at pre-flight. Rewriting the same body would create noise without changing a fact, so this stage records the verified state and leaves the PR Draft and `NOT_READY`.

## Current gate matrix before Candidate 3

| Gate | Entry status | Evidence meaning |
|---|---|---|
| ordinary CI | `PASS` | Current baseline only; Candidate 3 has not been tested. |
| 20 x 10W/100J correctness | `PASS` | Candidate 2 source-bound correctness evidence. |
| state/version/lease/fencing | `PASS` | Candidate 2 source-bound correctness evidence. |
| 20:1 / 8W fairness | `FAILED` | Secondary first committed receipt was position 4; frozen maximum is 2. |
| complete targeted repetitions | `NOT_RUN` | Candidate 2 stopped during repetition 1. |
| current 1k/10k/100k capacity | `NOT_RUN` | Fairness prerequisite failed. |
| same-runner comparison | `NOT_RUN` | Targeted/capacity prerequisites failed. |
| current A-I x3 fault | `NOT_RUN` | Downstream prerequisite failed. |
| current formal 32-arm | `NOT_RUN` | Downstream prerequisite failed. |
| release manifest | `INCOMPLETE` | Partial or historical evidence cannot fill current Candidate 3 stages. |

## Environment limitation discovered

The Windows host has no `docker`, `postgres`, `psql`, or `pg_isready` executable and port `127.0.0.1:5432` is closed. Consequently, a real-PostgreSQL RED cannot execute locally on this host. Local checks can still collect/skip the integration test and run unit/static checks. The authoritative RED/GREEN concurrency execution must use the repository's PostgreSQL-backed GitHub Actions job; this limitation must be recorded rather than replacing PostgreSQL with SQLite or mocks.

## Decision

Pre-flight is complete. Candidate 3 is authorized exactly once by this stage's governing task. Nothing here establishes Candidate 3 correctness or performance, and no tag, release, merge, threshold change, workload change, or Candidate 4 is authorized.
