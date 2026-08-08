# AI EvalOps negative results

See `NEGATIVE_RESULTS.md`. Formal load run `gate1-gh-31174970193-1` is retained but rejected because
Git line-ending normalization changed `final/summary/arms.csv` after the manifest was created. Failed,
partial, and invalidated attempts will not be removed from the record. Run
`gate1-gh-31176423383-1` passes bundle hash verification but is rejected for capacity reporting because
eight arms have incomplete required Prometheus evidence.

Tenant-fair claiming run `31252705647` is also retained as failed evidence. Its new fixture violated
Tenant/APIKey insert ordering, and its first locking policy regressed the existing concurrent batch
claim from 100 Jobs to 20. Neither intended fairness number is admitted from that run.

Correction run `31253257533` is also retained as failed evidence. A CTE candidate became running
while its outer query waited for a lock; missing outer eligibility revalidation led to a rejected
`running -> running` transition. The intended fairness assertion still did not complete.
