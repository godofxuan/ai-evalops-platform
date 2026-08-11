# Portfolio Archive Execution Log

Date: 2026-08-11

Task: final portfolio closure, Teaching Codex, Resume Codex and interview package

Scope lock: documentation/evidence only; scheduler candidate budget 0; measurement candidate budget 0

This log records what changed, why, problems encountered, the response and the resulting effect.

## Phase 1 — Re-lock repository and evidence state

### Action

- fetched remote state, checked out `codex/evidence-gate-1`, inspected status/branch/HEAD/log;
- confirmed clean baseline `39f381e8369e044392fbad39c3fbc75d5bdeb942` and remote synchronization;
- reread release, evidence-contract, fairness, attribution, measurement, learning, handoff, scripts and `app/jobs` surfaces.

### Why

The attached task explicitly prohibited copying historical prompt facts into final documents. The branch and checked-in
artifacts had to be the authority.

### Problem encountered

`PROJECT_STATUS.md` did not exist, while several handoff/resume/teaching files reflected earlier phases and stopped before
the final passive measurement result.

### Response

Created one canonical status page and made newer authoritative handoffs link back to it; retained old files with explicit
historical/superseded notices instead of deleting history.

### Effect

Current state—bounded PASS, frozen fairness PASS, negative scaling, invalid measurement, H1/H2/H3 inconclusive, NOT_READY,
Draft PR, no production readiness and zero candidate budgets—is visible before any deep technical narrative.

## Phase 2 — Local verification and environment diagnosis

### Action and exact results

- system `python --version`: Python 3.13.5;
- system `python -m pip check`: exit 0, no broken installed packages;
- system `python -m compileall app scripts tests`: exit 0;
- system `python -m pytest -q`: exit 4 with 55 collection errors;
- project `.venv\Scripts\python.exe -m pytest -q`: 783 passed, 33 skipped in 467.06 seconds.

### Why

Syntax compilation and full tests answer different questions. A portfolio metric must come from the project environment,
while an unexpected command failure must remain visible and explained.

### Problem encountered

The system interpreter lacked project dependencies/plugins (`structlog`, Redis client, FastAPI, psycopg, boto3,
OpenTelemetry and the pytest asyncio option). `pip check` only proved the packages installed in that interpreter were
internally consistent; it did not prove project dependencies were installed.

### Response

Did not install or mutate the system interpreter. Reran the exact suite with the repository `.venv` (Python 3.12). Recorded
both outcomes in the metric ledger. The 33 skips explicitly require real PostgreSQL/Redis/MinIO integration flags that the
local machine does not provide.

### Effect

The local code suite is green in the correct environment, while external-service verification remains a CI responsibility
and is not falsely described as a local pass.

## Phase 3 — Independent metric and manifest recalculation

### Action

- imported all four targeted `arms.csv` files;
- independently summed arm/Job/protected-counter fields and grouped 20:1 receipt positions by worker count;
- read assessor `self_scaling` rather than prior prose;
- rehashed every target and passive-measurement manifest entry by relative path, file size and SHA-256;
- recomputed historical fault-matrix totals from 18 summary rows.

### Why

Resume numbers are particularly easy to copy after their scope has drifted. Every number needed a reproducible source and
allowed/forbidden wording.

### Problems encountered

- The assessment schema stored scaling under `self_scaling`, not under each `groups` entry as initially queried.
- Manifest `files` was a JSON object; a naïve PowerShell `.Count` printed one count per property instead of the total.
- Telemetry summaries used `successful_sample_count`, `rows_written`, etc., not the first assumed property names.

### Response

Inspected object keys, changed the queries to the actual schema, counted `PSObject.Properties`, and summed the correct
telemetry fields. No artifacts were edited during calculation.

### Effect

Verified independently:

- 64 arms; 6,400/6,400/6,400 submitted/unique/terminal;
- every protected counter zero;
- fair position 2 and legacy 953 for all 16 skew observations;
- ratios 0.782511 / 0.772797 / 0.796214 / 1.014063;
- targeted manifest 598/598 and passive manifest 151/151, both with zero missing/size/hash mismatch;
- historical fault summary 54/54 successful controlled repetitions, zero recorded violations;
- passive telemetry 69 successful, 65 wait-observing, 5,393 rows, zero error/drop/overflow.

## Phase 4 — Recruiter-facing portfolio closure

### Action

- added README Recruiter Quick View and kept the existing engineering deep dive;
- created `PROJECT_STATUS.md`, `PROJECT_EVIDENCE_MAP.md` and `RECRUITER_SUMMARY.md`;
- updated README and cross-surface state with passive measurement invalidity.

### Why

The release blocker was previously hundreds of lines into README. A recruiter should see the system, strongest evidence and
negative release result without losing access to engineering depth.

### Problem encountered

Several old surfaces ended at the second synchronous observer and said no third automatic attempt. A later separately
authorized passive qualification had in fact run, so leaving the text unchanged would create a misleading current state.

### Response

Preserved the historical statement but added the separately authorized passive run, exact numbers and final stopped state.

### Effect

README now says plainly: release intentionally blocked, v0.1.0 NOT_READY, PR Draft and production readiness not verified.

## Phase 5 — Teaching and interview system

### Action

- created the authoritative `TEACHING_CODEX_HANDOFF.md`;
- wrote ten modules, each containing Concept, Project implementation, Source code, Failure mode, Test, Evidence, Trade-off,
  Interview question, Reference answer, Follow-up question and Common wrong answer;
- created ten full interview stories with Problem through What I learned;
- superseded the old compact Teaching update and marked the long scheduler file as historical chronology.

### Why

A README explains what exists; it does not guarantee the learner can reason about a stale-worker race, `SKIP LOCKED`
semantics, evidence independence, negative scaling or observer effect under interview follow-up.

### Effect

The learner has a code/test/artifact-backed path from data model fundamentals through stop decisions, plus a graduation
checklist that blocks unsupported resume claims.

## Phase 6 — Current JD research

### Action

Reviewed 14 company career/formal employer job pages across AI Evaluation, AI Platform, Backend APIs and Distributed
Systems; tagged semantic responsibility presence and mapped it to VERIFIED/PARTIAL/NO_EVIDENCE project state.

### Why

Role language should come from current employers, but a keyword may enter the resume only when project evidence supports it.

### Problems encountered

- Exact Anthropic searches did not return in a bounded time; those roles were excluded rather than reconstructed from memory.
- Cohere’s formal Ashby page required JavaScript in the text fetch; it is flagged for re-verification before an application.
- Several roles demand production Kubernetes, on-call, SLO, incident response and capacity planning, which this project does
  not evidence.

### Response

Used only directly accessible official/formal pages for detailed extraction, kept a source link/access date, labeled the
Cohere limitation, and classified unsupported operations keywords as NO_EVIDENCE.

### Effect

The strongest defensible targeting is Eval infrastructure, AI/Python backend and bounded distributed correctness. Staff SRE/
compute roles expose concrete future gaps instead of becoming keyword stuffing.

## Phase 7 — Resume package and consistency gate

### Action

- created four position variants, each with 3 primary and 2 backup bullets;
- created `RESUME_METRIC_LEDGER.md` and 20-bullet interview consistency audit;
- created the eight-file `resume_package/` quick handoff;
- added a historical warning to old `docs/resume_materials.md`.

### Why

Resume Codex needs a small authoritative package, and every compressed bullet must expand back into an interview-defensible
mechanism, calculation and limitation.

### Problem encountered

A broad patch initially failed safely because the old resume file’s actual Chinese title differed from the assumed title.
No partial changes were applied. The patch was split, the exact title was inspected, and then the historical warning was
added separately.

### Effect

Resume and interview claims now share the same evidence. Forbidden claims, unsupported JD keywords and project/RAG overlap
are explicitly blocked.

## Phase 8 — Pending final closure

Before final decision, run link/structure/state checks, compile/test smoke checks, commit the three documentation groups,
push the branch, wait for final GitHub branch/PR CI and confirm PR remains Draft. Record the final identities below rather
than editing prior evidence artifacts.
