# Dataset provenance and limits

Frozen file: `benchmarks/external_harness_v1/cases.json`

- Cases: 9
- Categories: grounded answer, citation correctness, tool selection, multi-step behavior, insufficient evidence, permission denial, budget exhaustion, tool failure, prompt-injection resistance
- SHA-256: `8963cc0385af516d076d992497a02770c2fef3fc8e0039706d7d7b8a086a686c`
- Source: contract-focused prompts derived from the public RAG project documentation at the two exact Git SHAs
- Evidence class: `mechanism_ci`
- Formal quality gate eligible: **no**

This small set exists to exercise the contract and reporting pipeline. It is not the preregistered 100–200 case quality set requested for a production release decision. No claim about population quality, safety rate, or regression is permitted from it.
