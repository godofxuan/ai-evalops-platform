# Agent tool-use evaluation workflow

This extension answers a practical question: did an Agent merely produce the expected final
text, or did it use the right tools, with the right arguments, inside its authorization and tool
budget?

## Run it

```powershell
./.venv/Scripts/python.exe -m scripts.build_agent_tool_demo_dataset --verify
./.venv/Scripts/python.exe -m scripts.run_product_experiment `
  --spec benchmarks/agent_tool_demo_v1/experiment.json `
  --output-dir artifacts/agent-tool-demo
Start-Process artifacts/agent-tool-demo/report.html
```

The frozen dataset has 120 paired cases: 20 each for single-tool selection, multi-tool ordering,
argument validation, authorization, tool budget, and error recovery. Both arms run the exact same
case IDs. The result records ordered tool calls, arguments, status, terminal state, latency, cost,
and trace identity.

## Metrics and their direction

| Metric | Meaning | Better direction |
| --- | --- | --- |
| `agent_task_completion` | terminal state is completed and final answer matches | higher |
| `tool_selection_accuracy` | ordered tool-name sequence exactly matches | higher |
| `tool_argument_validity` | ordered names and JSON arguments exactly match | higher |
| `policy_violation_rate` | at least one tool is outside the allowlist | lower |
| `tool_budget_violation_rate` | call count exceeds budget or provider reports exhaustion | lower |
| `tool_error_rate` | provider or any tool call reports an error | lower |

Exact matching is intentional for this deterministic pack. Real semantic argument judging should
be added as a separately versioned evaluator and policy, not silently substituted.

## Evidence boundary

`DEMO_PASS` proves that the contract, paired execution, metrics, bootstrap core, trace report and
manifest work together. The fixtures deliberately contain baseline defects and candidate repairs.
They do not prove that a deployed Agent improved, do not replace blinded human review, and do not
authorize `FORMAL_AB_COMPLETE`, Shadow PASS, release, or production-readiness claims.
