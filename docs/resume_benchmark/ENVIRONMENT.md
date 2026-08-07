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

Observed during formal run `gate1-gh-31177702100-1`; the complete capture is retained at
`docs/results/load/gate1-gh-31177702100-1/environment/runner.txt`.

| Field | Observed value |
|---|---|
| GitHub Actions run | `31177702100`, attempt `1` |
| Frozen source SHA | `15e7ac2e28b70430acd0bff88ee6cc78e5b86a86` |
| OS/kernel | Linux x86_64, Azure kernel `6.17.0-1020-azure` |
| CPU | 4 logical CPUs; AMD EPYC 7763; 2 cores / 4 threads |
| Memory | 16,766,423,040 bytes total |
| Docker Engine | `28.0.4`, Linux/amd64 |
| Docker Compose | `v2.38.2` |
| Application image | `sha256:d42299d56dd18551b9abf8fc0eda58e38c03182fe9f007e57122f40bac197319` |
| Python in image | `3.12.13` |

This is an isolated, shared-class CI runner rather than production hardware. Results characterize
this exact container topology and resource envelope; they are not a production SLO or capacity
guarantee.
