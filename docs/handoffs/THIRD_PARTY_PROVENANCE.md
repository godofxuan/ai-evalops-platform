# AI EvalOps Platform — Third-party provenance review

Reviewed: 2026-08-20

Branch: `codex/final-evidence-hardening-v1`

Implementation baseline: `22fda896a1b24b0cf41cd1402ead521f74758ac6`

## Method and decision rule

This is a repository-evidence review, not a claim about model training data or a legal opinion. The review inspected
`pyproject.toml`, `uv.lock`, repository-root license/NOTICE files, relevant file headers/comments, Agent/MCP documentation,
the fixed benchmark fixture, implementation paths and Git history. It did not infer copying from naming, style or API
similarity. When the repository could not establish origin, the classification is `UNKNOWN`.

No copied or adapted third-party source was established by the inspected repository evidence. Confirmed use is ordinary
SDK/library API usage plus a concept-level compatibility fixture. The repository currently has no root `LICENSE`, `NOTICE`
or `COPYING` file; that does not violate a dependency merely by existing, but it leaves the public repository's own reuse
terms unspecified and prevents a clean redistribution conclusion. This task deliberately does not choose a project license.

## Component review

| Project component / path | External source | URL | Usage type | External license | Attribution / NOTICE requirement | Current compliance | Evidence | Action | Open risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `app/agent_eval/mcp_server.py`, `mcp_stdio.py` | Official MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk | `API_USAGE` | MIT | Retain MIT notice when copying/substantially redistributing SDK source; ordinary dependency metadata remains in lockfile | Dependency and version are declared/locked; no copied SDK source or upstream copyright header found | `pyproject.toml` has `mcp>=2,<3`; `uv.lock` pins `mcp==2.0.0`; imports `mcp.server.MCPServer`; official repository identifies MIT | Keep the upstream URL/license here; reassess if SDK example code is ever copied into the repository | This review did not perform a full transitive-license/SBOM legal analysis |
| MCP tool registration and stdio launch pattern | MCP SDK documentation/examples as API reference | https://github.com/modelcontextprotocol/python-sdk/tree/main/docs | `API_USAGE` | MIT | Same as SDK; copied example blocks would require retaining applicable notice | No byte-for-byte or adapted example provenance was established; implementation delegates into project-specific authorization/control-plane code | File history is project-local Codex-authored commits; no “copied/adapted from” header; tool names map to this repository's services | If a contributor later identifies an adapted example, change classification to `ADAPTED` and add attribution | Git history cannot prove that no unrecorded reference was consulted |
| `app/agent_eval/benchmark.py` LangGraph callback-name mapping | LangGraph callback concepts/names | https://github.com/langchain-ai/langgraph | `CONCEPT_ONLY` | MIT | MIT notice applies to copied/substantial source; API/callback names alone do not establish copied code | LangGraph is not a declared/locked runtime dependency; fixture uses locally constructed dictionaries and fixed events | `pyproject.toml`/`uv.lock` contain no `langgraph` package; `_adapt_langgraph` maps four callback-style labels; `docs/agent_eval/BENCHMARK.md` limits scope | Keep wording as “LangGraph-style compatibility fixture” | Cannot establish which public callback documentation, if any, originally informed the mapping |
| `benchmarks/agent_eval_v1/cases.json`, `docs/agent_eval/adapter_comparison_evidence.json` | Agent evaluation harness ideas | No concrete upstream source recorded | `UNKNOWN` | `UNKNOWN` | Unknown until a concrete source is identified | Cases/evidence are repository-local and hash-bound, but absence of attribution is not proof of independent origin | Git history introduces deterministic adapter evidence in commit `27fb175`; no source URL/header was found | Contributors must disclose any copied/adapted harness source before reuse; then record URL, revision, license and notice | Concept provenance cannot be reconstructed from current history |
| Exactly eight adapter case families | Custom-controller and LangGraph-style event replay | Repository-local fixture | `CONCEPT_ONLY` | Project license currently unspecified | No third-party NOTICE identified | Scope is accurately described as fixed fixture replay, not a live framework benchmark | `docs/agent_eval/BENCHMARK.md`; canonical checked-in evidence; no live LangGraph package | Preserve the fixed fixture replay limitation in README/resume/teaching | Public reuse terms for the repository itself remain unspecified |
| Trajectory schema, deterministic metric extractors, regression/review/reconciliation services | Possible public Agent/EvalOps design influence | No concrete upstream implementation recorded | `UNKNOWN` | `UNKNOWN` | Unknown; cannot invent attribution | No copied/adapted third-party code was established from headers/history | Project-specific migrations/tests and sequential project commits; no upstream URL or copyright header | Reclassify only on concrete evidence; do not state “independently invented” | Repository evidence cannot prove the complete idea history |
| Claude Code assistance | Claude/Anthropic coding assistance | No repository record tying Claude to specific code | `UNKNOWN` | Not applicable to dependency licensing; output ownership/use depends on applicable service terms | Do not invent training sources or private prompts | Search found no Claude attribution in relevant implementation/history | No matching code header/commit attribution in inspected paths | If maintainers have an external activity log, summarize only non-sensitive facts in a future review | Current repository cannot establish whether Claude assisted any specific file |
| Codex assistance across Agent final-hardening commits | OpenAI Codex coding assistance | Git history (repository-local) | `UNKNOWN` for third-party code origin; confirmed tool assistance | Not an incorporated open-source dependency | Honest authorship disclosure; do not publish prompts, secrets, local paths or claim the tool made acceptance decisions | Git commits are authored `Codex <codex@localhost>` and execution logs identify Codex; no external source attribution is implied | `git log -- app/agent_eval docs/agent_eval benchmarks/agent_eval_v1`; project execution logs | Interview wording below; retain human/project-owner responsibility and evidence-based acceptance | Tool assistance does not identify training sources or prove originality of every line |
| Python runtime dependencies generally | PyPI packages declared and hash-locked | https://pypi.org/ | `API_USAGE` | Multiple; package-specific | Package-specific licenses/notices; redistribution must be checked for the chosen artifact/image | Direct/transitive versions and hashes are present in `uv.lock`; no consolidated NOTICE/SBOM is checked in | `pyproject.toml`, `uv.lock`, container definitions | Before a distributable release, generate/review an SBOM and license inventory and add the chosen project license | This focused audit is not a complete transitive or container-layer license audit |

## MCP and LangGraph conclusions

- MCP is a real declared dependency and is used through the official Python SDK API. The implemented and tested transport
  is local stdio. The upstream SDK may support other transports, but this project does not thereby implement Streamable
  HTTP, OAuth resource-server behavior or a remote rate limiter.
- LangGraph is not a runtime dependency here. The adapter maps four LangGraph-style callback names over deterministic fixed
  inputs. It is fixed fixture replay, not a live LangGraph runtime, integration qualification or performance benchmark.
- No row is classified `COPIED` or `ADAPTED` because the inspected evidence did not support either label. That is a bounded
  audit result, not proof that no contributor ever consulted public material.

## Honest interview attribution

Safe wording:

> AI coding tools, including Codex where recorded by Git history, accelerated implementation and documentation. The project
> owner defined the architecture, constraints, gates and acceptance criteria, reviewed the resulting code/tests/evidence,
> and accepted claims only when repository evidence supported them. The repository does not establish Claude involvement
> for a specific file and does not disclose private prompts or infer any model's training sources.

## Required follow-up before a distributable release

1. Choose and add a repository license through an explicit maintainer decision; this review does not make that choice.
2. Produce a version-bound direct/transitive dependency and container-image license inventory/SBOM.
3. Confirm whether any contributors used copied or adapted public harness/example code not recorded in Git history.
4. Add third-party notices only where the confirmed license/use mode requires them.
5. Repeat the review whenever a live framework adapter or network MCP transport is added.
# 2026-09-02 product-workflow research boundary

The usable paired-evaluation layer was designed after reviewing official repositories for
Langfuse (MIT outside separately marked `ee` paths), Phoenix (Elastic License 2.0), DeepEval
(Apache-2.0), Ragas (Apache-2.0), Promptfoo (MIT), OpenAI Evals (MIT), and Temporal (MIT).
No source from those projects was copied. The implementation uses original Pydantic contracts,
provider/evaluator protocols, paired evidence code, and portable report generation. Phoenix is
concepts-only because of ELv2; Langfuse enterprise paths are excluded. Optional package adapters
are deferred until a real metric justifies their dependency/model cost. The detailed adoption
matrix and official links are in [`OPEN_SOURCE_PRODUCT_BENCHMARK.md`](../review/OPEN_SOURCE_PRODUCT_BENCHMARK.md).
