# Agent Failure Taxonomy v1

This is intentionally a small taxonomy. A category is emitted only when a trajectory evaluator observes supporting
evidence; it is not an assertion of the ultimate model or infrastructure root cause.

| Category | Initial detector | Example | False-positive boundary |
| --- | --- | --- | --- |
| `tool_failure` | failed tool-result or `tool_error` terminal | tool returns an error | a provider error alone does not prove tool design is faulty |
| `permission_failure` | denied terminal or unauthorized result leak | Agent reads a denied document | a deliberate denied attempt without data leak is still policy behavior, not necessarily task failure |
| `grounding_failure` | unsupported claim event | answer claim lacks admitted evidence | absence of an automated label requires human review |
| `citation_failure` | citation marked invalid | cited source ID is invalid | citation formatting alone is not answer correctness |
| `loop_failure` | repeated identical tool calls | repeated same query/tool arguments | repetition may be intentional retry policy |
| `budget_failure` | `budget_exhausted` terminal | call/token budget reached | budget policy must be recorded to compare runs |
| `model_failure` | `agent_error` terminal | runtime reports Agent error | this is a bounded terminal classification, not model causal attribution |
| `human_review_required` | task success unavailable | no deterministic success oracle | reviewer packet decides quality |

The v1 enum also reserves retrieval, planning, context and infrastructure categories for a future evaluator with
concrete evidence. They are not emitted speculatively.
