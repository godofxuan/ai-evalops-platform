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

For a Custom Controller versus LangGraph Adapter comparison, freeze model, dataset version, retrieval corpus, tool
catalog, budget and prompt policy. Both adapters emit the same `agent-run-artifact/v1` schema, with only the framework
label differing. Compare success, citations, tool validity, steps, latency, usage, terminal distribution and failure
category distribution; do not assume either runtime must win.
