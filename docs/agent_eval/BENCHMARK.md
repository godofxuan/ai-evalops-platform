# Agent Evaluation Benchmark v1

The initial benchmark is deliberately small and deterministic. It is a contract for future source-bound runs, not a
claimed production-scale result.

| Case family | Expected behavior |
| --- | --- |
| direct lookup | answer with mapped citation |
| multi-step retrieval | use retrieval then cite admitted evidence |
| denied access | emit denied tool behavior and no unauthorized result leak |
| missing evidence | abstain, partial answer or request human review |
| conflicting evidence | expose uncertainty rather than inventing support |
| tool failure | bounded failure or retry behavior with terminal reason |
| budget limit | emit `budget_exhausted` terminal state |
| injection/adversarial | reject untrusted instructions and preserve policy boundary |

The executable fixture is `benchmarks/agent_eval_v1/cases.json`. The Custom Controller adapter maps controller-style
events directly; the LangGraph compatibility adapter maps LangGraph-style callback names to the same semantic event
types. Both emit `agent-run-artifact/v1` and are evaluated by the same seven deterministic evaluators.

Reproduce the checked-in evidence:

```text
python -m scripts.run_agent_adapter_benchmark
```

The generated `docs/agent_eval/adapter_comparison_evidence.json` is canonical JSON bound to the fixture SHA-256 and
each emitted artifact SHA-256. Current deterministic replay evidence covers 8/8 intersecting cases, reports task
success rate `0.875` on both sides, interpolated latency p95 of approximately `83 ms` on both sides and zero
unauthorized-result leaks. Correct denied-access behavior is classified for diagnosis but is not counted as a boundary
violation unless an unauthorized result was actually exposed.

This is an adapter-contract replay, not a live LangGraph-versus-custom runtime performance experiment. It uses fixed
events and supplied usage, so it cannot support throughput, scalability, model-quality or production-latency claims. A
future live comparison must freeze model, retrieval corpus, tool catalog, budget, prompt policy and dataset version,
then preserve raw runtime outputs instead of replacing this fixture’s purpose.
