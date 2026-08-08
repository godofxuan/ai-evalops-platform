# AI EvalOps résumé metrics

Status: approved quantitative claims are listed in `RESUME_SAFE_METRICS.md`.

Recommended concise wording:

> Built and evidence-tested a multi-tenant asynchronous AI evaluation platform. A 32-arm Docker
> Compose benchmark processed 16,000/16,000 Jobs successfully and measured 3.11× throughput speedup
> at eight Workers; a repeated nine-scenario fault matrix observed zero lost or duplicate Jobs and
> rejected all six deliberately stale terminal writes.

Use the longer scoped bullets in `RESUME_SAFE_METRICS.md` when a format allows context. Do not round
3.11× upward, call the scaling linear, or omit that the measurements are retained experiments.

Optional fairness wording:

> Added PostgreSQL-native tenant-fair job claiming; in a controlled real-PostgreSQL 20:1 backlog
> test, reduced the later tenant's claim position from 21 to within the first two claims without
> duplicate first-wave Jobs.
