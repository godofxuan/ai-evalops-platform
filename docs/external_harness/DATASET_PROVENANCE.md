# Dataset provenance and limits

Frozen file: `benchmarks/external_harness_v1/cases.json`

- Cases: 9
- Categories: grounded answer, citation correctness, tool selection, multi-step behavior, insufficient evidence, permission denial, budget exhaustion, tool failure, prompt-injection resistance
- Canonical JSON SHA-256: `08ccad71d7c96cdd2d558018b480a1e421abd3781527a828793aa4430d517d11`
- Source: contract-focused prompts derived from the public RAG project documentation at the two exact Git SHAs
- Evidence class: `mechanism_ci`
- Formal quality gate eligible: **no**

This small set exists to exercise the contract and reporting pipeline. It is not the preregistered 100–200 case quality set requested for a production release decision. No claim about population quality, safety rate, or regression is permitted from it.

The digest is computed over parsed JSON serialized with sorted keys and compact separators. It is stable across LF/CRLF and indentation changes while still changing when the dataset's semantic JSON content changes.
