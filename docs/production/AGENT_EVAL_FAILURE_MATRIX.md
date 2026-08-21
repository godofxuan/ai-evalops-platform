# Agent evaluation production failure matrix

| Failure | Expected behavior | Evidence | Current result |
|---|---|---|---|
| Malformed Inspect log | Reject before artifact creation | converter contract tests | PASS |
| Non-JSON RAG output | Reject and withhold stderr | `test_rag_subprocess.py` | PASS |
| Harness timeout | Raise classified execution error | `test_rag_subprocess.py` | PASS |
| Wrong producer Git SHA | Reject result | subprocess client identity check | MECHANISM_ONLY |
| Trace/case mismatch | Reject result | real-contract and trace tests | PASS |
| Duplicate artifact | Stable canonical hash; SQL uniqueness returns existing row | existing ingestion plus adapter hash tests | PASS |
| Telemetry exporter unavailable | Do not fail evaluation | `test_trace_correlation.py` | PASS |
| Permission denial | No content leak; classified terminal | frozen dataset case | NOT_EXECUTED_AB |
| Prompt injection in retrieved content | Reject instruction/evidence as policy requires | frozen dataset case | NOT_EXECUTED_AB |
| Budget exhaustion | Emit budget terminal state | frozen dataset case | NOT_EXECUTED_AB |
| Tool failure | Emit classified tool/system failure | frozen dataset case | NOT_EXECUTED_AB |

`MECHANISM_ONLY` means the branch contains the enforcement path but no production-like fault injection was run against both frozen RAG revisions. `NOT_EXECUTED_AB` is not a pass.
