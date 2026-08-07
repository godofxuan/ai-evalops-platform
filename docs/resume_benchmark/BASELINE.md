# Baseline

Recorded on 2026-08-07 (Asia/Shanghai).

## Frozen source state

| Field | Value |
|---|---|
| Target branch | `codex/evidence-gate-1` |
| Source commit | `18f995ebbb5d25475be305829ab609f7c63e2d3d` |
| Source subject | `docs(ci): record successful P2-9 validation` |
| Initial worktree | clean |
| Previous target SHA | `f6a3a2892d8f0f3e39336990debdade8858031c1` |
| Branch alignment | fast-forwarded by 108 commits; no merge commit, rebase, or reset |

## Local quality baseline

| Check | Exact result | Evidence classification |
|---|---|---|
| `uv lock --check` | resolved 70 packages; lock accepted | `PASS-local` |
| `ruff format --check .` | 262 files already formatted | `PASS-local` |
| `ruff check .` | all checks passed | `PASS-local` |
| strict mypy | 119 source files; no issues | `PASS-local` |
| non-integration pytest | 508 passed, 9 deselected, 2 warnings, 272.81 s | `PASS-local` |
| integration marker locally | 9 skipped, 508 deselected, 3.74 s | `SKIPPED-no-infra` |

The two pytest warnings came from Windows denying cleanup of old user-temp pytest garbage paths.
They were outside the repository, did not fail tests, and were not deleted or modified.

## Remote baseline

GitHub Actions run: <https://github.com/godofxuan/ai-evalops-platform/actions/runs/31174201772>

| Field | Value |
|---|---|
| Head SHA | `18f995ebbb5d25475be305829ab609f7c63e2d3d` |
| `compose-smoke` | success |
| `quality-and-integration` | success |
| Workflow conclusion | success |
| Completed at | `2026-08-07T11:30:38Z` |

Both jobs completed successfully against the exact frozen SHA. This is a quality and integration
baseline; it is not substituted for the pending load and failure-injection experiments.
