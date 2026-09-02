# Usable Eval Product v1 — execution log

Date: 2026-09-02  
Branch: `codex/usable-eval-product-v1`  
Starting point: clean `origin/main@aea8044061e678fb8e0d5312222987c5499ea83d`

## Goal and decision record

The goal is to convert a strong but backend-heavy evaluation platform into a workflow a reviewer
can run and understand. The scope includes official open-source research, exact RAG input audit,
a declarative paired experiment, automatic evaluators, a portable dashboard, formal evidence
boundaries, tests, teaching material, resume handoff, push, and exact-SHA CI.

The rejected scheduler candidate `5687fbdfcd0835ffdf1f1884ddaa27f8c411eb51` was checked and is
not an ancestor of this branch. The previous negative scaling evidence remains authoritative and
is not rewritten by this product work.

## Work performed and effects

| Stage | Why | Change | Problem encountered | Effect |
| --- | --- | --- | --- | --- |
| Clean branch | Prevent a failed scheduler implementation from leaking into product work | Created from exact clean `origin/main` | Existing work lived on mixed evidence branches | Product work has an auditable ancestry |
| OSS benchmark | Learn proven interaction patterns without license or architecture drift | Reviewed Langfuse, Phoenix, DeepEval, Ragas, Promptfoo, OpenAI Evals, Temporal | Phoenix is ELv2 and Langfuse has `ee` boundaries | Adopted concepts only; no copied third-party source |
| Formal core | Reuse already-tested local evidence code, not the rejected scheduler candidate | Cherry-picked independent formal-quality commit `3a67085` | Commit also contained preregistration history | Kept truthful historical context and executable paired statistics |
| RAG audit | Identify real producer identity and avoid fabricated formal input | Read exact remote refs and producer artifacts | Local RAG worktree is dirty from another task; existing A/B has only 5 mechanism cases | RAG stayed untouched; missing formal inputs are machine-explicit |
| RED tests | Freeze user-facing and evidence boundaries before implementation | Added strict spec, digest, 120-case, missing-credential, HTML-injection tests | `uv` was absent from PATH | Switched to the existing project venv; recorded environment issue separately |
| Product runner | Turn configuration into paired evidence | Added fixture/HTTP providers, deterministic evaluators, bounded concurrency, formal assessment | Strict Python list-to-tuple conversion failed in one test | Kept strict production validation and fixed the test input |
| Dashboard | Make the experiment understandable without running a frontend stack | Added portable dependency-free HTML with summary and case drill-down | Untrusted answers could contain HTML | Escaped every rendered value and added a regression test |
| Evidence outputs | Let another reviewer rehash the run | Added result, per-arm artifacts, HTML, and file manifest | Formal runs may lack credentials or reviewers | Emits `INPUT_REQUIRED`/`HUMAN_REVIEW_PENDING`; never invents PASS |

## Verification ledger (implementation stage)

| Command | Result |
| --- | --- |
| `python -m pytest -q -p no:cacheprovider tests/unit/product_experiments` | 7 passed |
| `python -m ruff check app/product_experiments tests/unit/product_experiments` | passed |
| `python -m mypy app/product_experiments` | passed |
| Extended product/formal-quality selection | 13 passed |
| `python -m scripts.build_product_demo_dataset --verify` | 120 cases, exact SHA verified |

Final implementation SHA, demo result digest, full-suite totals, push result, and exact GitHub CI
will be appended only after those events actually occur.

## Implementation and demo evidence

- Implementation SHA: `41de043f40c02c0d1349332c6bd19e9116202838`.
- Implementation CI: `33589528112`, successful (`quality-and-integration` 7m28s;
  `compose-smoke` 1m00s).
- Main promotion: remote `main` was re-fetched at
  `aea8044061e678fb8e0d5312222987c5499ea83d`, verified as an ancestor, then non-force
  fast-forwarded to the same implementation SHA. Rejected scheduler candidate
  `5687fbdfcd0835ffdf1f1884ddaa27f8c411eb51` was rechecked and is not an ancestor.
- Exact-main CI: `33590045034`, completed successfully for exact SHA
  `41de043f40c02c0d1349332c6bd19e9116202838`.
- Dataset SHA-256: `563a5063ae06efcd8b4a49729bf3621887b9876ffe34bc66bf41c0b6b2bb916c`.
- Result SHA-256: see `docs/results/product_demo_v1/manifest.json` (rehash-verified locally).
- Cases: 120 exact paired cases; six categories × 20; left-only 0; right-only 0.
- Demo metrics: task success `0.90 → 1.00`, citation correctness `0.90 → 1.00`,
  tool error `0 → 0`, p95 latency `46 → 50 ms`, mean cost `$0.010 → $0.011`.
- Task-success paired delta: `+0.10`; deterministic 95% interval `[+0.05, +0.1583]`.
- Product status: `DEMO_PASS`; statistical status `PASS`; evidence decision `INPUT_BLOCKED`;
  `formal_ab_eligible=false`; human review `PENDING`; production ready `false`.

Additional review caught and fixed two false-positive paths before evidence was accepted:

1. A demo's nested formal decision initially remained eligible. Eligibility is now an explicit
   input to the statistical contract and demo results fail closed at the formal gate.
2. A pure non-regression policy could accept two completely failed arms. The frozen policy now
   combines paired-delta rules with candidate task/citation absolute minimums (`0.80`) and a
   tool-error absolute maximum (`0.05`). A same-failure regression test proves the gate returns
   `FAIL`.

CI attempts `33588623313` and `33588682128` failed at formatting because a test file migrated
from the earlier formal-quality commit did not match the current Ruff formatter. The repository
was not allowed to bypass the check; the single file was formatted and the full repository now
reports `576 files already formatted`.

Browser-based visual QA was attempted through the Codex browser surface, but the host reported a
missing browser runtime asset path before a browser session could start. This is recorded as an
environment limitation. HTML safety and structure remain covered by automated escaping tests,
the report is generated successfully, and the independent file manifest verifies its bytes.

## Final evidence validation

The final local gate was intentionally rerun after the main-CI result was written into the
evidence documents:

- non-integration suite: `919 passed, 39 deselected` in 276.96 seconds;
- Ruff format and lint: passed (`576 files already formatted`);
- Mypy: passed for 192 source files;
- Python bytecode compilation: passed;
- final evidence manifest rehash: passed;
- product artifact manifest: `DEMO_PASS`, four files independently rehashed;
- focused evidence and portfolio-documentation tests: `8 passed`;
- `git diff --check`: passed, with only Git's expected CRLF-to-LF warning for the JSON manifest.

One verification command was initially invoked with an incorrect `--result-dir` option. The
verifier's actual interface accepts the manifest path as its positional argument. The incorrect
invocation exited at argument parsing before reading or changing evidence. It was corrected to
`python -m scripts.verify_product_experiment docs/results/product_demo_v1/manifest.json`, which
then verified experiment `paired-rag-product-demo-v1`, status `DEMO_PASS`, and all four files.

## Current RAG re-audit and aggregate import

After the first product closeout, the cross-project authority changed from the historical RAG
Final Pair SHA `2065e571...` to current `main@bd71cb3...`. The audit was reopened rather than
leaving a stale current-source claim. Read-only checks confirmed remote main, clean local
alignment, exact CI `33588082333` with four successful jobs, and R5 public artifact SHA-256
`97aa582d996194171004964acfbda46732f685998dd3227b3730a8b778c404ce`.

The first inspection guessed `docs/r5/RESULTS.md` and `PROTOCOL.md`; those files did not exist.
Enumerating the exact commit tree found the authoritative `ENGINEERING_JOURNAL.md` and two JSON
evidence files. No RAG file, ref, worktree or index was changed.

Because the real public R5 artifact contains aggregate metrics but intentionally omits per-case
payload, EvalOps gained a separate external aggregate verifier. It validates byte identity,
schema/source/protocol identity, paired-count arithmetic, Hit@5 derivation, interval estimates,
latency ratio, source gates, and claim boundaries; it rejects digest drift, private/per-case
keys, count drift, failed gates, and internally inconsistent outcomes. Focused validation passed
six tests, and the real artifact produced `AGGREGATE_EVIDENCE_VERIFIED` together with the
mandatory `FORMAL_CASE_RESULTS=INPUT_REQUIRED` boundary.

The isolated implementation commit was
`5f6aa5a996062d4423b94aa4f7c2a15c38fd41b3`. It was non-force fast-forwarded to `main`, and
exact-main GitHub Actions `33592493933` completed successfully before the final documentation
manifest was regenerated.

Final post-regeneration validation passed with `925 passed, 39 deselected` in 238.84 seconds,
Ruff format (`579 files already formatted`) and lint green, Mypy green for the 194-file formal
scope plus the new unit test independently, compileall green, product artifact verification
green, final evidence manifest verification green, and real R5 aggregate verification green.
The earlier single full-suite failure was the intended stale-manifest guard on the modified
`PROJECT_STATUS.md`; regenerating the manifest against the accepted implementation SHA resolved
it without weakening or skipping the test.
