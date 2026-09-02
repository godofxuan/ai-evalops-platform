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
