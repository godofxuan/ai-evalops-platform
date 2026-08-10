# v0.1.0 RC environment and reproducibility

The local Windows environment was used for deterministic bundle replay, Ruff, format, MyPy and unit tests. The
final local evidence-contract state passed 65 focused evidence tests and 633 complete unit tests. Pytest emitted one
warning because `.pytest_cache` was not writable; assertions and exit status were successful. Real PostgreSQL
qualification remained remote and was not substituted with local skips.

Authoritative schema-v2 execution used GitHub-hosted Linux with PostgreSQL/Redis/Compose:

| Protocol | Run | Source | Result |
|---|---:|---|---|
| ordinary push CI | `31351821014` | `91acdba...` | PASS |
| ordinary PR CI | `31351825433` | `91acdba...` | PASS |
| targeted repetition execution | step in `31352270523` | `91acdba...` | SUCCESS, 4/4 repetitions |
| targeted repeated assessment | `31352270523` | `91acdba...` | NEGATIVE_SCALING |
| artifact upload/evidence commit | `31352270523` | `15bab58...` | SUCCESS |

The preserved directory contains runner/source/Compose diagnostics, 64 raw arms, 512 raw EXPLAIN summaries, four
schema-v2 bundle manifests, four verified rep assessments, top-level assessment and a sealed top-level manifest.
Artifact `targeted-gh-31352270523-1` is 1,395,629 bytes with digest
`sha256:6b5f68821b90ee6bdbb36d66aba0087864ca2048ac356ec3cb701e378d0c120f`.

Historical schema-v1 run `31327388006` remains unchanged and failed. Historical capacity/formal/fault bundles
remain bound to their original sources and cannot substitute for current downstream qualification.
