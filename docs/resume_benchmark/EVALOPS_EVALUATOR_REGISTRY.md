# Evaluator registry and metric contract

Status: `LOCAL-GREEN` (remote CI pending)

## Decision before implementation

The repository already persisted the evaluator type, caller-declared version, configuration,
configuration hash, dataset version/hash, target version/configuration hash, and source commit for
each Run. It also already had two built-in implementations: lexical answer signals and operational
execution signals. The missing part was not another framework; it was an explicit, inspectable
registry and a retrieval/citation evaluator.

The minimum design therefore keeps the existing `Evaluator` protocol and adds one registry entry
per built-in evaluator. A registration owns both its descriptor and factory. This single-source
shape is intentional: separate metadata and factory maps can drift and falsely advertise an
evaluator that cannot be constructed.

An LLM judge was not added. Judge output is model-, prompt-, sampling-, and provider-dependent, and
would require a separate provenance and reliability contract. Silently mixing it with deterministic
metrics would make comparisons misleading. The registry explicitly marks every current entry as
`llm_judge=false`, and an `llm_judge` type is rejected.

## Registered evaluators

| kind | implementation version | category | output intent |
|---|---|---|---|
| `basic_answer` | `builtin-v1` | deterministic | lexical exact/normalized match, keyword coverage, answer/citation presence |
| `retrieval_citation` | `builtin-v1` | deterministic | retrieval recall and citation precision/recall/F1 against explicit source labels |
| `execution` | `builtin-v1` | operational | latency, token counts, attempt count, retry-success signal |

`execution` is deliberately classified as operational rather than deterministic answer quality.
Latency and token usage describe execution cost/behavior; they do not prove answer correctness.

## Retrieval/citation definitions

The dataset case supplies `metadata.relevant_source_ids`. The target supplies retrieved `sources`
and answer `citations`. IDs are compared as sets, so duplicate IDs cannot inflate a score.

- `retrieval_recall = |retrieved IDs ∩ relevant IDs| / |relevant IDs|`
- `citation_precision = |cited IDs ∩ relevant IDs| / |cited IDs|`
- `citation_recall = |cited IDs ∩ relevant IDs| / |relevant IDs|`
- `citation_f1` is the harmonic mean of citation precision and recall.

When citations are empty but relevance labels exist, citation precision/recall/F1 are `0.0`.
When relevance labels are absent, empty, or malformed, all four metrics are `null`. Returning zero
in that case would incorrectly treat missing ground truth as measured failure.

## Reproducibility boundary

The persisted Run fields provide a traceable tuple:

`source_commit + dataset version/hash + target type/version/config hash + evaluator type/version/config hash`

The registry adds an implementation descriptor (`builtin-v1`) at that exact source commit. This is
enough to locate the code and inputs used by a Run. The API's evaluator version is still a
caller-declared semantic field; it is persisted but is not yet a server-signed implementation
attestation. Requiring a new version enum now would change the existing API contract, so that is
recorded as a limitation rather than silently introduced in this stage.

## RED/GREEN evidence

The tests were written before implementation. The first collection failed because
`EvaluatorCategory` and `app.evaluators.retrieval_citation` did not exist. After the registry and
metric implementation were added, evaluator tests passed.

The first strict MyPy run then failed at `return factory()` because the unannotated constructor map
was inferred as returning `object`. The map was typed as `Callable[[], Evaluator]`, proving the
protocol boundary. A design review then found the metadata/factory drift risk; both were consolidated
into one internal registration object, and a regression test now constructs every advertised entry.

Local focused result:

- evaluator unit tests: `8 passed`;
- Worker + Run service compatibility tests: `19 passed`;
- focused Ruff: passed;
- focused strict MyPy: passed for 7 source files.
- complete non-integration suite: `570 passed, 12 deselected` in `367.06s`;
- repository Ruff: 303 files formatted and lint-clean;
- repository strict MyPy: passed for 129 source files.

These results prove the local contract only. The status must not be promoted to `VERIFIED` until the
complete repository gates and remote GitHub Actions pass for the committed revision.

## Known limitations

- No LLM judge implementation or judge provenance/repeatability study exists.
- Relevant-source labels are exact string IDs; no graded relevance or ranking metric (MRR/nDCG) is
  implemented.
- The current built-ins accept no evaluator-specific configuration beyond shared Worker controls.
- The registry is in-process Python, not a third-party package discovery or sandbox mechanism.
