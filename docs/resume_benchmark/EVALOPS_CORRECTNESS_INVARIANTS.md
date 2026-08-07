# AI EvalOps correctness invariants

Status: `PENDING` for the full real-service matrix.

The acceptance gate requires exact submitted/unique/completed/failed/lost counts, unique durable
`CaseResult` rows, a single terminal commit, no unexplained nonterminal Jobs, and zero accepted stale
result or failure submissions in deliberately induced fencing scenarios.
