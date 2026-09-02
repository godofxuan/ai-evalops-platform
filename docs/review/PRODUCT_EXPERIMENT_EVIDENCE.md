# Usable paired-evaluation product evidence

Status timestamp: 2026-09-02  
Branch: `codex/usable-eval-product-v1`  
Implementation SHA: `41de043f40c02c0d1349332c6bd19e9116202838`  
Implementation CI: [GitHub Actions 33589528112](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33589528112) — `SUCCESS`  
Default-main promotion: non-force fast-forward to the same SHA; [main CI 33590045034](https://github.com/godofxuan/ai-evalops-platform/actions/runs/33590045034) — `SUCCESS`

## What can be independently reproduced

```powershell
./.venv/Scripts/python.exe -m scripts.build_product_demo_dataset --verify
./.venv/Scripts/python.exe -m scripts.run_product_experiment `
  --spec benchmarks/product_demo_v1/experiment.json `
  --output-dir docs/results/product_demo_v1 `
  --evalops-sha 41de043f40c02c0d1349332c6bd19e9116202838
./.venv/Scripts/python.exe -m scripts.verify_product_experiment `
  docs/results/product_demo_v1/manifest.json
```

The verifier recomputes every listed file's byte size and SHA-256 and cross-checks experiment,
dataset, EvalOps, repository/arm, and status identities between `manifest.json` and `result.json`.

## Result

| Field | Exact observed value |
| --- | --- |
| Product status | `DEMO_PASS` |
| Statistical status | `PASS` |
| Formal evidence decision | `INPUT_BLOCKED` |
| Formal A/B eligible | `false` |
| Cases | 120 exact paired; 0 baseline-only; 0 candidate-only |
| Categories | basic, semantic, completeness, conflicting information, high level, information not found; 20 each |
| Dataset SHA-256 | `563a5063ae06efcd8b4a49729bf3621887b9876ffe34bc66bf41c0b6b2bb916c` |
| Common-case IDs SHA-256 | `75ea430877bcbe95cb7e479ab32593c6102db8dd67f212ddc4f920d8f657e0e0` |
| Metrics digest | `51df60137d0b4fd21e87522f197f3c077c2f02c761b1b1e6f5f786374f02a7c8` |
| Human review | `PENDING` |
| Production ready | `false` |

## Demo metric details

| Metric | Baseline | Candidate | Delta / relative delta | Deterministic 95% paired interval | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Task success | 0.90 | 1.00 | +0.10 | [+0.05, +0.1583] | pass |
| Citation correctness | 0.90 | 1.00 | +0.10 | [+0.05, +0.1583] | pass |
| Tool error rate | 0.00 | 0.00 | 0.00 | [0.00, 0.00] | pass |
| p95 latency | 46 ms | 50 ms | +8.70% | delta [4 ms, 4 ms] | pass |
| Mean cost | $0.010 | $0.011 | +10.00% | delta [$0.001, $0.001] | pass |

The data is intentionally synthetic and deterministic. It demonstrates that a known set of
baseline misses appears as case-level fixes while latency and cost budgets are enforced. It is
not a measurement of `Attempt-of-enterprise-rag-copilot` or another deployed target.

## Fail-closed controls demonstrated

- Strict versioned JSON config rejects unknown fields and literal credential fields.
- Dataset bytes are checked before provider construction or request execution.
- Baseline and candidate roles, repositories, source SHAs, cases, categories, and prompts are
  preserved in the result.
- HTTP mode uses HTTPS-only host allowlisting, DNS result validation, connection peer checking,
  redirect denial, bounded timeouts, and environment-only bearer credentials.
- Evaluators are selected from a code-owned registry; uploaded configuration cannot execute
  arbitrary evaluator source.
- Paired relative gates are combined with candidate absolute quality/error thresholds, so equal
  total failure is rejected.
- Demo calculations can pass, but demo evidence is explicitly ineligible for the formal gate.
- Untrusted answer/case content is escaped in the HTML report.
- Output mutation is rejected by an independent manifest verifier.

## Inputs not invented

Formal quality still requires two exact running RAG revisions, an unconsumed frozen 120+ case
dataset, any required provider/model spend approval, and two real independent reviewers. Until
those exist, the only valid release-facing decision is `INPUT_BLOCKED` followed by
`HUMAN_REVIEW_PENDING`; no Shadow or production claim is authorized.
