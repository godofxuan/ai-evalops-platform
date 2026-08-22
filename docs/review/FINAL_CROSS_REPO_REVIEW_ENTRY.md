# Final Cross-Repository Resume-Readiness Evidence

## Outcome

`FINAL_PAIR_CONTRACT_VERIFIED` for the exact pair:

- RAG: `godofxuan/Attempt-of-enterprise-rag-copilot@2065e571d77439babf76a763ac459a618950f218`
- EvalOps: `godofxuan/ai-evalops-platform@4040fa1db7cee6c8380ff8580fa21be17464435b`

The EvalOps implementation CI [32558950596](https://github.com/godofxuan/ai-evalops-platform/actions/runs/32558950596) and RAG CI [32555135411](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/32555135411) completed successfully for those exact SHAs.

## What changed, why, problems found, and effects

| Work package | Why | Problem encountered | Resolution and observed effect |
| --- | --- | --- | --- |
| Harness envelope | Producer Artifact integrity did not cover duplicated outer result facts. | Real RAG v1 contains additional durability/fencing fields, and citations live in `citation.checked` trajectory events rather than the outer artifact output. | Added envelope v1.1, canonical outer SHA-256, strict real-result fields and producer-authoritative projections. Exact pair converts 15/15 events with zero loss. |
| Projection checks | A re-sealed outer envelope could otherwise preserve a false duplicate fact. | Digest-only validation cannot prove agreement with the verified producer chain. | Answer, citation, terminal, policy, error and tool projections are independently compared; every mismatch fails closed with a specific error. |
| Evidence gate | A caller could previously supply a naked automated PASS. | Contract evidence could be mistaken for formal A/B evidence. | `FormalEvidenceDecision` binds dataset/policy/case/source identities and derives the outcome. Contract-only input remains `INPUT_BLOCKED` for Shadow and cannot emit PASS. |
| Audit delivery | Request-side retries depended on API-key validity and did not continuously drain all tenants. | Sink-success/ack-loss and multiple consumers risk repeated delivery. | Added a system-identity Dispatcher with `SKIP LOCKED`, lease/version fencing, deterministic sink identity, bounded backoff and DEAD_LETTER. Revoked keys no longer block historical audit delivery. |
| Deployment | A code-only dispatcher would not run in the actual topology. | The local environment had no Docker CLI, so Compose could not be proven locally. | Added CLI/runtime, Compose service, Prometheus scrape and CI checks. Exact GitHub CI proved Compose startup, migrations, observability and integration paths. |
| Final Pair | Prior candidate interop did not bind the final RAG and EvalOps revisions. | Mechanism cases must not be mislabeled as a quality dataset. | Ran 18 exact-SHA deterministic cases and emitted immutable case/result manifests. Result is only `FINAL_PAIR_CONTRACT_VERIFIED`. |
| Documentation | Canonical files contained old branches, SHAs and test totals. | Deleting old evidence would erase important negative scaling history. | Added a current snapshot to every required entry and retained old content explicitly as Historical. |

## Contract result

- Cases: 18.
- Source events: 15.
- Converted events: 15.
- Unmapped events: 0.
- Dropped events: 0.
- Outer digest: `edd044e7c984fa4c4166fab85994ac4187c6a0d008d253fba673f4df0e4ff7b5`.
- RAG output digest: `4d59e9ef6da53d48762c981cfdb4dac8404bd51d7297ad6ea039a6927edea5a4`.
- EvalOps artifact digest: `e3b917855bd7eaae2c290a500db84cc9abf406074765df3ce09d060861c1f8c6`.
- Dataset hash: `7a6705b94f31f2375677abcfd8e250c3c49d2e9c238f5fba44c130a6f50aecf4`.

## Honest release boundary

`IMPLEMENTATION_COMPLETE` and `PORTFOLIO_READY` do not mean merged, released or production-ready. Formal A/B was not run, human review remains pending, Shadow release remains input-blocked, and historical negative scheduler scaling remains binding.