# Resume benchmark evidence index

This directory is the human-readable index for evidence collected from real services. Raw,
machine-verifiable experiment bundles remain under `docs/results/`.

Evidence states are fail-closed:

- `VERIFIED`: backed by a retained raw artifact and a reproducible command;
- `FAILED`: the experiment ran and violated an invariant or collection requirement;
- `NOT-RUN`: no real-service execution exists yet;
- `UNKNOWN`: execution occurred, but the evidence cannot support a conclusion;
- `PENDING`: work is currently scheduled or in progress.

No performance number may be copied to the project README, résumé, or interview material until its
source row is `VERIFIED`.

## Files

- `BASELINE.md`: frozen Git and validation baseline;
- `ENVIRONMENT.md`: local and remote execution environments;
- `LOAD_RESULTS.csv`: per-arm real-service load results;
- `FAULT_RESULTS.csv`: real-service fault-injection results;
- `CONCURRENCY_RESULTS.csv`: real-service concurrency and fencing results;
- `RESUME_SAFE_METRICS.md`: only claims safe to reuse externally;
- `NEGATIVE_RESULTS.md`: failures, blockers, and invalid evidence;
- `EXECUTION_LOG.md`: chronological what/why/problem/effect record;
- `EVALOPS_*.md` / `EVALOPS_*.csv`: final consolidated deliverables.
