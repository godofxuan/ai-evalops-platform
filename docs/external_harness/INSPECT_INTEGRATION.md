# Inspect AI integration

## Outcome

EvalOps now has a real `inspect-ai` dependency group, an executable `Task`, and a fail-closed converter from an official `EvalLog` into `agent-run-artifact/v1`. The CI task uses a deterministic, model-free solver. It proves SDK/log/converter interoperability only; it is not evidence of RAG answer quality.

## Boundary

`app/external_harness/inspect_task.py` owns Inspect-specific Task and Solver code. `app/external_harness/inspect_adapter.py` converts a Pydantic `EvalLog` or its JSON representation. The core artifact schema remains framework-neutral. Unknown log status, missing identity, missing samples, malformed output, or non-JSON values stop ingestion.

The RAG producer is accessed through its versioned stdin/stdout CLI contract. `RagHarnessSubprocessClient` never invokes a shell, bounds runtime and stdout, withholds stderr from raised errors, validates the complete result, and requires the producer-reported Git SHA to equal the frozen requested SHA.

## Evidence levels

1. `test_inspect_runtime.py`: executed official `inspect_ai.eval`, converted the resulting `EvalLog` — mechanism evidence.
2. Local candidate smoke at `e848d8e...`: executed the real RAG CLI and observed policy decisions, tool events, artifact hash, and propagated trace — candidate interoperability evidence.
3. Frozen A/B quality comparison — not executed because baseline `909a971...` has no harness 1.0 contract.

## Commands

```powershell
.codex-tools\Scripts\uv.exe sync --locked --all-groups
.venv\Scripts\python.exe -m pytest tests\unit\external_harness -q
.venv\Scripts\python.exe -m human_review.validate_reviews --allow-pending
```

Inspect references: https://inspect.aisi.org.uk/, https://inspect.aisi.org.uk/tutorial.html, https://inspect.aisi.org.uk/agent-bridge.html
