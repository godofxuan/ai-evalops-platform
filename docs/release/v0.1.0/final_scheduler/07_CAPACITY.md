# Final scheduler capacity disposition

Date: 2026-08-09

Status: `NOT_RUN_TARGETED_FAIRNESS_FAILED`

The required current-candidate 1k/10k/100k capacity workflow was not triggered. Targeted run `31319556885` failed the
frozen 20:1 fairness contract before completing its four repetitions: the secondary Tenant's first durable claim was
position 4 at 8 workers, while the contract requires position `<= 2`. The sprint requires targeted PASS before
capacity, so executing the larger queues would violate the experiment order and consume CI without making the
candidate releasable.

Historical 1k/10k/100k bundles remain immutable and useful as historical engineering evidence. They do not qualify
source `246252e` or the final Candidate 2 plus Run-lock fix. In particular, the historical 100k single-Tenant/w8
observation of about `0.628 Jobs/s`, 504 retries and about 41 seconds claim p95 remains a negative historical result;
it is neither overwritten nor represented as a current measurement.

Current-candidate capacity values:

| Queue | Status | Reason |
|---:|---|---|
| 1k | `PARTIAL_TARGETED_ONLY` | 12/16 arms in repetition 1; not a capacity qualification |
| 10k | `NOT_RUN` | targeted fairness gate failed |
| 100k | `NOT_RUN` | targeted fairness gate failed |

No current 1k/10k/100k capacity claim is resume-safe.
