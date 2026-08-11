# Role Positioning

## A — AI Evaluation / EvalOps

Lead with evaluation workflow, immutable identity/provenance, evaluator registry, evidence contract, reproducibility and the
release gate. Best match to evaluation-infrastructure roles.

## B — AI Platform / Python Backend

Lead with FastAPI/PostgreSQL Run/Job orchestration, tenant-derived identity, Worker/Reaper state machine, result/artifact
transactions and bounded reliability evidence.

## C — Distributed Systems

Lead with lease/version/Attempt fencing, competing Reapers, durable fairness and the deterministic `SKIP LOCKED` false-empty
race. State at-least-once and bounded scope explicitly.

## D — Reliability / Infrastructure

Lead with fail-closed CI evidence, source/workload/manifests, fault testing, negative performance gate and measurement-system
qualification. Do not imply production SRE/on-call experience.

## Project separation

This project owns backend orchestration/concurrency/release evidence. The separate RAG project owns retrieval, grounding,
citation, Agent/Guard and multi-document failure attribution.
