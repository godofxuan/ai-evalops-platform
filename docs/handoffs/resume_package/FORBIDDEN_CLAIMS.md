# Forbidden Claims

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

Safe replacements:

- “at-least-once execution with fenced durable result persistence in tested paths”;
- “passed the exact frozen 20:1 receipt-position contract”;
- “the release gate blocked v0.1.0 after 3/4 scaling workloads failed”;
- “measurement qualification failed, so causal hypotheses remain inconclusive”;
- “implemented/tested observability; production operation not established.”
