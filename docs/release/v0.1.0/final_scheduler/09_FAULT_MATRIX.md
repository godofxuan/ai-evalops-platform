# Final scheduler fault-matrix disposition

Date: 2026-08-09

Status: `NOT_RUN_TARGETED_FAIRNESS_FAILED`

The current-candidate A-I × 3 fault matrix was not triggered. The mandated order is targeted PASS, capacity PASS,
then current fault evidence. Because targeted run `31319556885` failed the 20:1 fairness contract, no downstream run
can promote Candidate 2.

The existing 27/27 historical A-I evidence remains valid for its source and continues to support the platform's
historical recovery design: zero lost Jobs, duplicate CaseResults, duplicate terminal commits, orphan running Jobs and
invariant failures; stale success and stale failure attempts were observed and zero were accepted. It must be labeled
`VERIFIED_HISTORICAL`, not current scheduler evidence.

Current-candidate fault status is `NOT_RUN`; historical fault values are not copied into the current release gate.
