# Gate 0 raw evidence summary

Run ID: `gate0-20260729T200900+0800-a95f484`

Baseline SHA: `a95f484d0d2e0f659a442efa5b8d4ad6ddece644`

This file preserves command-level outcomes. It is a summary of terminal evidence, not a
replacement for a machine telemetry archive. No formal 500-case run was started.

## Repository observation

- `AGENTS.md`: absent.
- Required README, `pyproject.toml`, `uv.lock`, docs 00–13, engineering journal, Phase 9
  execution/environment records, `app`, `scripts`, `tests`, `alembic`,
  `deploy/compose.yaml`, and CI workflow were inspected.
- Source inventory at the baseline: `app` 88 Python files/9,175 lines; `scripts` 9/1,214;
  `tests` 63/6,477; `alembic` 9/1,115.
- Initial Git observation: `main`, clean tracked worktree, HEAD `a95f484...`.
- A later observation showed branch `codex/evidence-gate-0` at the same HEAD. Gate 0 did
  not run a branch creation or switch command.

## Commands and results

| Area | Command or probe | Result | Evidence |
|---|---|---|---|
| Lock | `.codex-tools/Scripts/uv.exe lock --check` | 60 packages resolved, exit 0 | `VERIFIED` |
| Environment | `uv sync --locked --all-groups --dry-run` | 58 packages checked; no changes | `VERIFIED` |
| Format | `python -m ruff format --check .` | 199 files already formatted | `VERIFIED` |
| Lint | `python -m ruff check .` | all checks passed | `VERIFIED` |
| Types | `python -m mypy app scripts tests/integration tests/concurrency` | 103 files, no issues | `VERIFIED` |
| Tests, default temp | `python -m pytest -m "not integration"` | 222 passed, 6 deselected, 13 setup errors | `FAILED` |
| Tests, clean temp | same selection with fresh `--basetemp` and `-p no:cacheprovider` | 235 passed, 6 deselected | `CONTRACT_VERIFIED` |
| Real integrations | `EVALOPS_RUN_INTEGRATION=1 ... pytest -m integration` | 6 selected; connection waits exceeded two minutes and were terminated | `FAILED` |
| PostgreSQL TCP | bounded connect to `127.0.0.1:5432` | unreachable within 2 seconds | `FAILED` |
| Redis TCP | bounded connect to `127.0.0.1:6379` | unreachable within 2 seconds | `FAILED` |
| Alembic | `python -m alembic heads` | `20260729_0008 (head)` | `VERIFIED` |
| Alembic | `python -m alembic history --verbose` | one chain, eight revisions | `VERIFIED` |
| Alembic | `python -m alembic upgrade head --sql` | PostgreSQL SQL generated from base to head; transaction committed | `VERIFIED` |
| Compose | `docker compose ... config/up` | `docker` CommandNotFound | smoke `NOT_RUN` |
| Metrics contracts | targeted metrics/API/durable tests | 5 passed | `CONTRACT_VERIFIED` |

The first pytest result is intentionally retained. The clean-temp rerun isolates the failure
to the pre-existing repository basetemp/cache permissions; it does not erase the default
command failure.

## Environment snapshot

- OS: Microsoft Windows 11 Pro, `10.0.26200`, build 26200, 64-bit.
- CPU: AMD Ryzen 5 7500F, 6 physical cores/12 logical processors.
- Physical memory: 33,947,549,696 bytes total; 13,151,168 KiB free at snapshot.
- Free disk at snapshot: C 28,210,819,072 bytes; D 72,570,888,192 bytes.
- Project Python: CPython 3.12.13. Global Python 3.13.5 is outside the project contract.
- uv: 0.11.32.
- Docker/PostgreSQL/Redis CLIs: not found on PATH.
- Compose configuration pins PostgreSQL `18.4-alpine3.24` and Redis
  `8.8.1-alpine3.23`; these are configured image tags, not observed runtime versions.

## Current Prometheus contract

Logical metric catalogue:

1. `api_request_total`
2. `api_request_duration`
3. `run_created_total`
4. `job_queue_depth`
5. `job_running`
6. `job_succeeded_total`
7. `job_failed_total`
8. `job_retry_total`
9. `job_lease_expired_total`
10. `worker_heartbeat_age`
11. `case_duration`
12. `sse_connections`
13. `redis_publish_failures_total`

The API exposes `/metrics`; Worker and Reaper use separate process-local registries on
ports 9101 and 9102. API labels are bounded to method, normalized route, and status;
tenant/run/job/attempt IDs are not metric labels. Compose enables metrics and binds worker
and reaper metrics only inside the Compose network. No Prometheus server, live multi-replica
scrape, service discovery, or alert evaluation ran in Gate 0.

## Failures and blockers

1. Repository-default `.pytest-tmp` could not be removed on Windows, producing 13 setup
   errors. A fresh system basetemp passed all 235 non-integration contracts.
2. Real PostgreSQL/Redis integration could not complete because neither local port was
   listening.
3. Compose smoke could not start because Docker/Compose is absent.
4. Runtime PostgreSQL/Redis versions, image IDs, container resource limits, and live
   configuration remain unknown until an infrastructure-capable host is used.

## Code/test changes

No production, test, migration, script, dependency, or deployment semantics were changed.
Only Gate 0 evidence and a Gate 1 protocol draft were added after collection.
