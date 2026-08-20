# Interview Stories

Current branch: `codex/final-evidence-hardening-v1`. These are `INTERVIEW_ONLY`; negative scheduler/measurement stories are
also `HISTORICAL_NEGATIVE`. Use current Agent stories as support for `CURRENT_POSITIVE_RESUME`, not as extra bullets.

Use the full [`INTERVIEW_STORY_BANK.md`](../INTERVIEW_STORY_BANK.md). Current and historical hooks:

1. Job/Attempt separation makes at-least-once retry history auditable.
2. Owner/version/expiry/Attempt fencing rejects stale Workers.
3. Competing Reapers recover expired leases transactionally.
4. Durable fair rounds move a 20:1 secondary tenant from position 953 to 2 in frozen scope.
5. A deterministic real-PostgreSQL RED→GREEN fixes `SKIP LOCKED` false-empty.
6. Evidence contract v2 replaces producer self-attestation with raw-plan assessment.
7. A preregistered negative scaling result blocks release.
8. Three measurement designs are rejected for observer effect.
9. H1/H2/H3 remain inconclusive instead of receiving forced narratives.
10. Candidate budgets stop Candidate 4 and preserve credibility.
11. Canonical immutable trajectory evidence separates content identity from truth authority.
12. Common-case regression manifests fail closed on insufficient evidence.
13. Hash-bound staged review reduces reviewer anchoring without claiming objective labels.
14. MCP stdio revocation is rechecked per call rather than trusted for a whole process.
15. Grace/recheck reconciliation compensates for non-atomic PostgreSQL/object-store operations.

Every answer must include Problem, Risk, Hypothesis, Implementation, Experiment, Evidence, Decision, Limitation and Learning.
