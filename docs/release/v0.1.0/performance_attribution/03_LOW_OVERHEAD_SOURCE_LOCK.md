# Low-overhead instrumentation source lock

- Recorder and exact-arm runner implementation commit:
  `63c8fa9ac56f1fb69850e25ae5f4d53f3ce006ac`
- Overhead-arm assessor contract commit:
  `0fd5376300155ee4fdfa3cfd248d636bdeca3100`
- Final requalification code lock:
  `0fd5376300155ee4fdfa3cfd248d636bdeca3100`
- Requalification preregistration commit:
  `785272d`
- Scheduler-behaviour baseline remains:
  `c5e8368e6588b7684a87e44d15c99e0d320744a7`

The allowed implementation delta after the previous diagnostic is limited to:

1. avoiding monotonic-clock reads for counter-only or ignored claim markers while preserving all
   registered timings and counters; and
2. selecting one exact arm already present in the frozen benchmark plan.

No `app/` change occurred. No scheduler SQL, durable state, fairness policy, retry/backoff, pool,
lease, queue, batch, Worker, distribution, sample-size, threshold or repetition setting changed.

The workflow trigger commit may change only workflow, trigger, source-lock and documentation files
after the implementation commit. The workflow verifies that `app/` and `scripts/` have no later
delta before starting PostgreSQL.

The execution SHA will be the immutable `GITHUB_SHA` of the trigger commit and will be checked by
every bundle. A passing overhead gate permits only the already preregistered formal attribution
matrix. It cannot change release readiness or authorize a scheduler candidate.
