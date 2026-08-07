# Environment

## Local coordination host

| Field | Observed value |
|---|---|
| OS/shell | Windows / PowerShell |
| Workspace | `D:\文档\ai-evalops-platform` |
| Docker CLI | not installed (`CommandNotFound`) |
| Real local PostgreSQL/Redis stack | not configured for this experiment |
| Consequence | local real-service load and disruption runs are `NOT-RUN` |

Installing system software was not inferred from the experiment request. The formal run is instead
scheduled on an isolated GitHub-hosted Linux runner that already provides Docker and Compose.

## Remote evidence runner

The exact OS, CPU, memory, free disk, Docker version, Compose version, image IDs, service inventory,
and source SHA will be retained inside the run directory after execution. Until that artifact exists,
these fields remain `PENDING`; GitHub's generic runner specification is not substituted for observed
runtime facts.
