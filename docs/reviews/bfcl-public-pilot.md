# BFCL public Python single-turn pilot

## Selection and provenance

This pilot uses the BFCL V4 checkpoint explicitly named by the official
[leaderboard](https://gorilla.cs.berkeley.edu/leaderboard.html):
`f7cf7359b7ac615a0b294831c5ba2bc95ee4a000` in
[ShishirPatil/gorilla](https://github.com/ShishirPatil/gorilla/tree/f7cf7359b7ac615a0b294831c5ba2bc95ee4a000/berkeley-function-call-leaderboard).
The upstream Apache-2.0 license is retained in `upstream/LICENSE` alongside the
downloaded, byte-for-byte original sources. No benchmark questions or gold labels
were edited. Exact source paths and SHA-256 digests are in the adapter constants
and frozen pilot manifest. Runtime loading rejects changed source or gold bytes.

Before observing local-model outputs, rank rows in each category by
`sha256(f'{SOURCE_SHA}/{category}/{id}')`, then select the first 25 in each of
`simple_python`, `multiple`, `parallel`, and `irrelevance`. This gives 100 fixed
cases from upstream category populations of 400, 200, 200, and 240 respectively.
This is a deterministic hash-stratified pilot, not an official full leaderboard
score. Public cases may have appeared in training data; no contamination-free
claim is made. Do not discard hard, malformed, timeout, or safety-rejected cases.

The frozen `cases.json` SHA-256 is
`e95152b4eb86a2bc7b14b582af439a64b89e323a99ed85f1cf57b59b8f9f6446`.
Each row retains its original ID, source index, question, schema, category, gold,
and generated messages. Only `messages` may be sent to a model. Initial first-N
preflight files are retained under `preflight-first-n-*`; they were replaced by
the planned hash-stratified selection **before any model inference** and are not
part of the final pilot. No scores influenced selection.

## Prompt and grading scope

Messages use original official `_func_doc_language_specific_pre_processing` and
`system_prompt_pre_processing_chat_model` functions with the official default:
`ret_fmt=python&tool_call_tag=False&func_doc_fmt=json&prompt_fmt=plaintext&style=classic`.
The Python-language hint is included. Responses are textual Python-style calls,
not native Ollama function-calling mode. No proposed tool or business action runs.

The full BFCL package imports numerous model SDKs and non-Python parsers.
Installing these exceeds the task scope. Instead, the adapter verifies original
files and selects their original AST nodes into an isolated namespace. Function
bodies and Python AST score logic are unchanged. The Python execution closure
contains original enums, prompt constants/helpers, Python output decoder helpers,
AST checker functions, and the irrelevance entry checker. Imports, model backends,
Java/JavaScript/XML branches and the full CLI are not used. A prompt-mode model
mapping preserves dotted function names; it is transport configuration, not a
claim that these local model versions appear in the upstream model registry.

The precise claim is **local Ollama inference on a pinned BFCL public Python
single-turn subset, scored with pinned upstream Python AST checker functions**.
Do not shorten this to “official BFCL pass” or compare its aggregate directly
with the full BFCL leaderboard.

## Safety issue found during integration

Pinned upstream `resolve_ast_by_type` evaluates `BinOp` expressions and one
`Lambda` branch with Python `eval`. Arbitrary model output must not reach these
paths. The adapter therefore performs an AST safety preflight, rejects those
nodes, bounds response length/AST complexity, and disables dynamic execution and
file/import builtins in the loaded namespace. **No model output is executed.**

Rejected output has `valid=false`, `official_valid=null`, and
`adapter_safety_rejected=true`, and remains in the denominator. This is explicitly
an adapter safety outcome, not a fabricated official-checker result. Unsupported
languages or expressions are not silently approximated with a custom score.

Upstream irrelevance rules classify non-call syntax, including decoding failures,
as no function call. The pilot preserves that behavior for nonempty responses
and separately records `parse_failed` and diagnostics. A natural-language refusal
can pass irrelevance while not parsing as a call. This does not establish refusal
quality, reasoning quality or correct clarification. Missing/empty transport
output is an adapter failure, never a free irrelevance pass. Any stricter local
format metric must be separately named; it must not replace the official metric.

## Reproduction and validation

Use the project's Python 3.12 locked environment, without new dependencies:

```powershell
python -m scripts.prepare_bfcl_pilot --root artifacts/public-benchmark-20260912/bfcl --download
python -m pytest tests/unit/public_benchmarks/test_bfcl.py -q
```

Preparation uses fixed-source HTTPS downloads, verifies every hash, and refuses
to overwrite the frozen pilot with different bytes. It never calls a model.
The experiment runner owns model digests, settings, request/response capture,
timeout accounting, paired ordering, and every fixed-case outcome.
`load_official_checker(source_dir)` loads the verified closure once;
`grade_case(case, raw_output, source_dir, checker=checker)` gives detailed results
without modifying the case or gold.

Safety tests run without downloads. Upstream-backed tests additionally run real
pinned functions on genuine public rows: wrong values/types/functions, missing
arguments, order-independent parallel calls, irrelevance, empty output, immutable
inputs, malicious-expression rejection and frozen-sample reproducibility. Their
manually specified expected responses are checker regressions, not model results.
When public sources are absent these tests explicitly skip, never claim a pass.

## Resume evidence boundary

Evidence must retain the fixed denominator, exact local model digests, all
category results, paired disagreement cases, local latency/token measurements,
parsing/transport failures, and source/result hashes. A higher model score is a
target-model comparison, not proof that EvalOps increased model intelligence.
The platform contribution is reproducible, auditable comparison and failure
accounting. Write an accuracy improvement only after the real experiment
establishes it; otherwise state demonstrated capability and sample counts.
