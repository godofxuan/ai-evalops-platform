# Resume / Interview Consistency Audit

Updated: 2026-08-20 on `codex/final-evidence-hardening-v1`. Every candidate bullet in `RESUME_CODEX_HANDOFF.md` must survive this table. Reference answers are in
`TEACHING_CODEX_HANDOFF.md`; STAR-like outlines are in `INTERVIEW_STORY_BANK.md`.

## Current Agent claims — `CURRENT_POSITIVE_RESUME`

| Bullet | Likely follow-up | Required defensible answer / evidence | Status |
| --- | --- | --- | --- |
| AE1 trajectory identity | What does SHA prove; why not verified truth? | canonical bytes, immutable ingestion, reported/derived provenance | `READY` |
| AE2 regression | Why common cases; what happens with low coverage? | immutable manifest; exact/intersection/allow-diff; sufficiency fail-closed | `READY` |
| AE3 review | How is blind review enforced? | source/result/artifact/packet hashes; staged evaluator visibility | `READY` |
| AE4 MCP | Why reauthenticate every call? | real stdio revoke test; local stdio only; no remote/OAuth claim | `READY` |
| AE5 reconciliation | Can a blob still be orphaned? | grace/recheck/retry/audit; database/object store are not atomic | `READY` |
| AE6 tenant evidence | Is RLS production-complete? | composite FKs/context tests; shared Compose role limitation | `READY` |

## Scheduler claims — `INTERVIEW_ONLY` / `HISTORICAL_NEGATIVE`

| Bullet | Likely follow-up | Required defensible answer / evidence | Status |
| --- | --- | --- | --- |
| A1 | Why separate Run/Job/Attempt/Result? | Module 1; ORM models; Run/Dataset tests | `READY` |
| A2 | How were 64/6,400 calculated? Why trust them? | Ledger calculation; schema v2; 598-file manifest | `READY` |
| A3 | Why 0.95 and why did 3/4 block release? | preregistration, exact ratios, release decision | `READY` |
| A-B1 | Why is faster ON invalid? | absolute gate; three perturbations; H1–H3 NOT_RUN | `READY` |
| A-B2 | Which identities/outputs are auditable? | evaluator registry, Run bindings, Result/Artifact models | `READY` |
| B1 | Why PostgreSQL authority and Redis lossy? | architecture, SSE snapshot/fallback, atomicity boundary | `READY` |
| B2 | Why isn’t Worker ID enough? | owner/version/expiry/Attempt; stale tests/counters | `READY` |
| B3 | How do two Reapers avoid double recovery? | `FOR UPDATE SKIP LOCKED`; at-least-once; historical scope | `READY` |
| B-B1 | Can client choose tenant? Is RLS complete? | server-derived Principal; shared-owner bypass | `READY` |
| B-B2 | How are artifacts deduplicated? | blob/reference split; no DB/object atomic transaction | `READY` |
| C1 | Exactly-once business effect? | explicitly no; external side-effect limit | `READY` |
| C2 | Reproduce race without sleeps; remaining window? | event-controlled lock; exists probe; no universal liveness | `READY` |
| C3 | How is position measured; starvation-free? | exact 20:1 vectors and explicit “no” | `READY` |
| C-B1 | Which counters; deadlock proof? | ledger’s seven counters; no deadlock-free claim | `READY` |
| C-B2 | What can hash prove; why raw EXPLAIN? | integrity not signature; independent semantics | `READY` |
| D1 | Give one fail-closed mutation. | source/arm/plan/counter/manifest adversarial tests | `READY` |
| D2 | Why keep NOT_READY; why no Candidate 4? | stop rule and researcher freedom | `READY` |
| D3 | Why reject passive telemetry? | perturbation association only; no cause | `READY` |
| D-B1 | Is 54/54 current or universal? | no; historical controlled scenarios | `READY` |
| D-B2 | Production on-call/SLO/capacity? | no; implementation/test evidence only | `READY` |

## Automatic rejection rules

Reject a bullet if the candidate cannot explain its calculation, design alternative, race/failure test and evidence path;
why execution is not exactly-once; why release remains NOT_READY; why H1/H2/H3 remain inconclusive; or why Candidate 4 was
stopped. Also reject any bullet requiring production operation, Kubernetes, on-call, achieved SLO, production capacity,
universal fairness or a proved root cause.

Also reject “seven verified evaluators,” all-framework/live-LangGraph claims, remote/OAuth MCP, atomic PostgreSQL/S3,
complete production RLS isolation or any current-positive use of the historical 783/33 local total.
