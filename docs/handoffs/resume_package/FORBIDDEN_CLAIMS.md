# Forbidden Claims

Current branch: `codex/final-evidence-hardening-v1`. This is the `FORBIDDEN` tier; positive wording belongs in
`CURRENT_POSITIVE_RESUME`, replacements in `JD_SPECIFIC_BACKUP`, and negative evidence in
`INTERVIEW_ONLY`/`HISTORICAL_NEGATIVE`.

Do not write any of the following unless future evidence materially changes:

- production-ready / production-scale / enterprise-grade production;
- exactly-once execution or universal zero data loss;
- universal fairness / strong fairness / starvation-free;
- deadlock-free;
- linear scaling / highly scalable / production capacity;
- proved or identified the scheduler root cause;
- achieved SLO, production on-call or incident-response experience;
- Kubernetes/GPU/streaming experience from this project;
- complete tenant isolation or security certification.
- seven verified evaluators or independently verified Agent truth;
- every Agent framework or a live LangGraph runtime/performance benchmark;
- Streamable HTTP/OAuth/remote MCP or remote rate limiting;
- atomic PostgreSQL/S3 or two-phase commit.

Safe replacements:

- “at-least-once execution with fenced durable result persistence in tested paths”;
- “passed the exact frozen 20:1 receipt-position contract”;
- “the release gate blocked v0.1.0 after 3/4 scaling workloads failed”;
- “measurement qualification failed, so causal hypotheses remain inconclusive”;
- “implemented/tested observability; production operation not established.”
