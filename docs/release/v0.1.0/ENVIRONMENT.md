# v0.1.0 RC environment and reproducibility

The local Windows host has no Docker, PostgreSQL client/server or reachable port 5432. Local PostgreSQL tests were
therefore collected and explicitly skipped; they were never reported as passed. Local Candidate 3 checks were Ruff
format (369 files), Ruff lint, MyPy (136 source files) and a 100-test high-risk subset. Two full non-integration
wrapper attempts timed out at approximately 124s and 304s without an assertion report and are recorded as
environment-limited, not PASS.

Authoritative Candidate 3 execution used GitHub-hosted Linux with real PostgreSQL/Redis/Compose:

| Protocol | Run | Source | Result |
|---|---:|---|---|
| ordinary push CI | `31327012832` | `02f5e68…` | PASS |
| ordinary PR CI | `31327016117` | `02f5e68…` | PASS |
| targeted qualification | `31327388006` | `02f5e68…` | FAILED evidence contract |

The targeted runner record contains Linux 6.17.0-1020-azure, Python 3.12.13, Docker 28.0.4 and Compose 2.38.2.
Its directory preserves `runner.txt`, `source.txt`, `compose-ps.txt`, bounded `compose.log`, raw arms, 128 raw
EXPLAIN summaries, manifests and assessment files. The GitHub artifact `targeted-gh-31327388006-1` has digest
`sha256:b9db8fc934b3e736c5a30868833218cc470ab011fcfa24f12dc4892cdfe47a1a`; Git commit `90a4e03`
preserves the same evidence in the branch.

Historical capacity/formal/fault bundles remain source-bound to `9987a28`, `6acf72c` and `70a9b2b`. Their runner
and protocol records are preserved but cannot substitute for Candidate 3 downstream qualification.
