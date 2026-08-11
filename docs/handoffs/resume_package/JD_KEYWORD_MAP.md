# JD Keyword Map

Research authority: [`JD_RESEARCH_2026-08-11.md`](../JD_RESEARCH_2026-08-11.md), 14 formal postings.

| Keyword family | Classification | Resume use |
| --- | --- | --- |
| evaluation infrastructure / reproducibility | `VERIFIED` | yes |
| Python / FastAPI / PostgreSQL | `VERIFIED` | yes when JD asks |
| backend APIs / platform services | `VERIFIED` | yes |
| distributed concurrency | `VERIFIED_BOUNDED` | yes with race/test scope |
| orchestration / scheduling | `VERIFIED_IMPLEMENTATION` | yes; no hyperscale claim |
| testing / CI / automation | `VERIFIED` | yes |
| observability / measurement | `VERIFIED_IMPLEMENTATION` | yes; no production ops claim |
| reliability | `PARTIAL` | failure handling/testing only, no SLO |
| identity / security | `PARTIAL` | tenant/API permissions only, no certification |
| control plane / data plane | `PARTIAL` | explainable architecture, no large-scale operation |
| scalability | `NO_EVIDENCE_FOR_POSITIVE_CLAIM` | use negative release-gate story only |
| incident response / on-call / SLO | `NO_EVIDENCE` | exclude |
| capacity planning | `NO_EVIDENCE` | exclude |
| Kubernetes / GPU / Kafka-scale streaming | `NO_EVIDENCE` | exclude |

Tailoring rule: keyword presence in a JD does not authorize it in a resume; project evidence must authorize it too.
