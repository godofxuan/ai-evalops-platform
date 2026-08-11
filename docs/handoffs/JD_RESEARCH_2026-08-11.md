# Current JD Research — AI Evaluation / Platform / Backend / Distributed Systems

Research date: 2026-08-11. Sources are company career pages or the company’s formal Ashby/Lever job pages. Job availability
changes; re-open the source before a real application. Counts below use one semantic presence per posting, not raw word
occurrences. No “hot skills” blog was used.

## Sample: 14 current formal postings

### AI Evaluation / Agent Evaluation

1. [OpenAI — Backend Software Engineer (Evals)](https://openai.com/careers/backend-software-engineer-%28evals%29-san-francisco/): reliable/reproducible/extendable eval pipelines, continuous regression/drift monitoring, golden datasets, backend APIs; explicitly names Python, FastAPI, Postgres and distributed systems.
2. [OpenAI — Simulation Infrastructure Engineer](https://openai.com/careers/simulation-infrastructure-engineer-san-francisco/): automated evaluation pipelines, orchestration, APIs, metrics, artifact versioning, reproducibility and runtime reliability.
3. [Epoch AI — Software Engineer, Benchmarking](https://jobs.lever.co/epoch-ai/d172645e-a11f-44a0-88d0-7a989e0a28f6): maintain evaluation infrastructure, integrate providers, implement/run benchmarks and make outputs accurate/trustworthy.
4. [Waabi — Senior Software Engineer, Evaluation Infrastructure](https://jobs.lever.co/waabi/12c40987-656a-4ec3-9fc0-3c0801c74238): evaluation tooling/pipelines, metrics/tags, Python, data processing, distributed compute, reliable services, job orchestration, monitoring and instrumentation.
5. [Datadog — Staff Applied Scientist, Agentic Interfaces](https://careers.datadoghq.com/detail/7964141/?gh_jid=7964141): reusable agent-evaluation datasets, golden traces, regression harnesses, latency/cost/end-to-end success metrics and measurement systems.
6. [OpenAI — Principal Software Engineer, Simulation](https://openai.com/careers/principal-software-engineer-simulation-san-francisco/): APIs and operational patterns connecting agentic production harnesses to training/evaluation environments with reliability and correctness.

### AI Platform / Backend Infrastructure

7. [OpenAI — Backend Software Engineer, API Enterprise Controls](https://openai.com/careers/backend-software-engineer-api-enterprise-controls-san-francisco/): authentication/identity, key management, auditability, observability, operational controls and reliable platform APIs.
8. [OpenAI — Software Engineer, Infrastructure — Core Experimentation](https://openai.com/careers/software-engineer-infrastructure-core-experimentation-seattle/): distributed control plane, server evaluation paths, ingestion/analytics, performance, correctness, SLOs, incident response and capacity planning.
9. [Cohere — Software Engineer, Agents & Automations](https://jobs.ashbyhq.com/cohere/4a3c3eb2-ae2e-4a86-a677-7bdecbc7d76e): workflow builder/execution engine, integrations, debugging, observability, evaluation systems and feedback loops. The formal page is JavaScript-rendered; verify its text again before tailoring an application.
10. [FieldAI — Data Platform Engineer, Infrastructure](https://jobs.lever.co/field-ai/f41fb1ac-d266-4e2c-8879-2d88d6f890d4): distributed pipeline execution and ML evaluation jobs, IAM, observability, SLO/on-call/incident response and capacity planning.

### Python Backend / Backend APIs

11. [Stripe — Backend Engineer, Privy](https://stripe.com/careers/listing/backend-engineer-privy/7235875): backend platform primitives/APIs, data models/migrations, distributed systems, identity/security, reliability, scalability and performance. The posting’s stack is not Python-first.
12. [Stripe — Backend/API Engineer, Money as a Service](https://stripe.com/careers/listing/backend-api-engineer-money-as-a-service/7369543): design/maintain APIs and large systems, reliability/efficiency, critical production debugging and cloud services; interview is language-agnostic.

OpenAI Evals and Waabi are also the strongest language match in this category because both explicitly request Python; OpenAI
Evals additionally names FastAPI and Postgres. Cross-listing does not increase the unique sample count.

### Distributed Systems / Infrastructure

13. [OpenAI — Software Engineer, Compute Infrastructure](https://openai.com/careers/software-engineer-compute-infrastructure-san-francisco/): scheduling, orchestration, control/data planes, reliability, observability, benchmarking, failure modes and disciplined measurement at large scale.
14. [Datadog — Senior Software Engineer, Streaming Platform](https://careers.datadoghq.com/detail/7993551/?gh_jid=7993551): resilient client/control-plane interaction, high-throughput distributed paths, performance, observability and reliability.

Supplementary comparison only: [Datadog — Staff Software Engineer, Logs Observability Pipelines](https://careers.datadoghq.com/detail/7743369/?gh_jid=7743369) strongly emphasizes distributed systems, high-throughput processing, customer-cloud operation and capacity planning. It is not counted in the 14 because its production/cloud depth is materially beyond this project’s evidence.

## Semantic frequency across the 14 postings

The tags were assigned once per posting after reading responsibilities/qualifications. Counts are directional tailoring data,
not labor-market statistics.

| Skill / responsibility family | Posting presence | Project evidence | Classification |
| --- | ---: | --- | --- |
| Reliability / correctness / maintainability | 13/14 | State machine, fenced writes, Reaper, protected counters, fail-closed assessors | `VERIFIED` in tests/controlled experiments; no production SLO |
| APIs / backend/platform services | 11/14 | FastAPI Run/Dataset/Result/Review APIs, service/repository boundaries | `VERIFIED` |
| Testing / automation / reproducibility | 11/14 | 783-pass local suite, CI workflows, source-bound experiment/manifest automation | `VERIFIED` |
| Evaluation / experimentation / measurement | 10/14 | evaluator registry, frozen eval runs, evidence gates, measurement qualification | `VERIFIED` |
| Performance / latency / scalability | 10/14 | latency/throughput measured; formal scaling result is negative | `PARTIAL`; scalable-system claim is `NO_EVIDENCE` |
| Monitoring / observability / debugging | 9/14 | metrics/traces/logs and measurement telemetry, Compose/CI contracts | `VERIFIED` implementation; production operation `NO_EVIDENCE` |
| Distributed systems / concurrency | 8/14 | lease/version fencing, competing Reapers, durable fair rounds, race tests | `VERIFIED` within bounded scope |
| Orchestration / scheduling / runtime | 7/14 | durable Job/Attempt/Worker/Reaper and scheduler | `VERIFIED` implementation; hyperscale runtime `NO_EVIDENCE` |
| Data pipelines / artifacts / provenance | 7/14 | immutable Dataset Version, Run/Job/result/artifact and evidence manifests | `VERIFIED` |
| Identity / permissions / security | 5/14 | API keys, server-derived Principal, tenant constraints, human-review roles | `PARTIAL`; enterprise IAM/security certification absent |
| Control plane / data plane | 4/14 | API/scheduler versus Worker/Target/result path can be explained | `PARTIAL`; no large-scale control-plane operation |
| Incident response / on-call / SLO | 4/14 | no real on-call rotation, incidents or achieved SLO | `NO_EVIDENCE` |
| Capacity planning / production operation | 4/14 | frozen CI benchmarks and negative gate are not capacity planning | `NO_EVIDENCE` |
| Python | 4/14 explicit or accepted | Python 3.12 project; async FastAPI/SQLAlchemy/psycopg | `VERIFIED` |

## Responsibility-to-project evidence map

| JD language | Project state | Safe use |
| --- | --- | --- |
| evaluation infrastructure / reproducible eval pipelines | `VERIFIED` | Lead AI Evaluation version with workflow, evaluator registry, immutable identity and evidence gate. |
| backend services and APIs | `VERIFIED` | Lead Backend version with async Run/Job orchestration and tenant-scoped APIs. |
| distributed correctness / concurrency | `VERIFIED_BOUNDED` | Use lease/fencing/Reaper and deterministic false-empty race; always state tested scope. |
| testing / CI / automation | `VERIFIED` | Use suite/CI/evidence assessor, but do not equate unit count with production reliability. |
| monitoring / observability | `VERIFIED_IMPLEMENTATION` | Mention metrics/traces and measurement qualification; no “operated production observability.” |
| reliability | `PARTIAL` | Say explicit failure handling and bounded fault tests; no uptime/SLO claim. |
| identity / permissions / security | `PARTIAL` | Say tenant-derived identity/constraints; mention shared-owner RLS limitation if asked. |
| low latency / scalability | `NO_EVIDENCE_FOR_POSITIVE_CLAIM` | The honest story is the frozen gate blocked release; do not claim scalable/high-performance. |
| incident response / on-call | `NO_EVIDENCE` | Exclude from resume. Learning familiarity is not experience. |
| capacity planning / production operation | `NO_EVIDENCE` | Exclude. Frozen benchmark ≠ production capacity. |
| Kubernetes / GPU / streaming systems | `NO_EVIDENCE` | Exclude even when a target JD repeats it. Docker Compose is not Kubernetes experience. |

## Tailoring conclusions

1. **Best fit:** AI Evaluation Infrastructure and Python Backend/AI Platform roles that value eval reproducibility,
   orchestration, APIs, PostgreSQL correctness, testing and evidence.
2. **Credible adjacent fit:** distributed backend/reliability roles when the bullet leads with fencing, Reaper, deterministic
   races and fail-closed release gates—not large-scale production operations.
3. **Current gap:** Staff/SRE/compute roles whose core screen is Kubernetes production operation, on-call/incident response,
   SLO ownership, capacity planning or proven high-throughput scale.
4. **ATS rule:** use a JD keyword only when the project map labels it VERIFIED/PARTIAL and the bullet preserves that scope.
