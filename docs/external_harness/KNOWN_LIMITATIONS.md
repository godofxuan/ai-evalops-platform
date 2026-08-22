<!-- FINAL-CROSS-REPO-CLOSEOUT:START -->
> Status vocabulary: `IMPLEMENTATION_COMPLETE` · `EXACT_SHA_CI_REQUIRED` · `FINAL_PAIR_CONTRACT_REQUIRED` · `NOT_MERGED` · `NOT_RELEASED` · `PORTFOLIO_READY` · `FORMAL_AB_NOT_RUN` · `HUMAN_REVIEW_PENDING` · `SHADOW_RELEASE_NOT_PASSED` · `PRODUCTION_NOT_VERIFIED`.
>
> Exact implementation CI and Final Pair are satisfied for the bound implementation SHA; any reviewed evidence commit still requires its own exact-SHA CI. Contract evidence is not formal A/B, Shadow PASS, release, or production verification.
<!-- FINAL-CROSS-REPO-CLOSEOUT:END -->

# External Harness Known Limitations

1. The Final Pair suite has 18 deterministic mechanism/contract cases; it does not estimate answer-quality, latency, cost or failure-rate deltas for a formal baseline/candidate population.
2. `formal_ab_executed=false`; no 100–200 case symmetric A/B or bootstrap quality conclusion was produced.
3. Human review is `PENDING`; no reviewer agreement or Cohen's Kappa is claimed.
4. Shadow release is `INPUT_BLOCKED`, not PASS; no canary or production release was run.
5. Exact CI and Compose evidence validate a controlled topology, not production capacity, SLOs, on-call readiness or security certification.
6. PostgreSQL and S3/MinIO do not share an atomic transaction; reconciliation is compensation, not two-phase commit.
7. Execution and external tool effects remain at-least-once where the target does not supply its own idempotency control.
8. Historical negative scheduler scaling and measurement-validity results remain binding and were not rerun in this closeout.
9. The candidate branch is not merged, tagged or released.