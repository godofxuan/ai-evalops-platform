# 架构图

```mermaid
flowchart LR
    C["Client / CI / Experiment scripts"]
    API["FastAPI API<br/>auth · idempotency · query"]
    PG[("PostgreSQL<br/>durable source of truth")]
    REDIS[("Redis Pub/Sub<br/>ephemeral progress")]
    ART["Content-addressed<br/>local artifacts"]
    W["Worker replicas<br/>claim · heartbeat · evaluate"]
    R["Reaper<br/>expired lease recovery"]
    SSE["SSE clients"]
    PROM["Prometheus scraper"]
    OTEL["OpenTelemetry Collector<br/>(optional, not bundled)"]

    C -->|"Bearer API key + Idempotency-Key"| API
    API -->|"Run/Job transaction<br/>tenant-scoped queries"| PG
    API --> ART
    API -->|"snapshot first"| SSE
    REDIS -->|"live events"| API
    API -->|"SSE stream"| SSE

    W -->|"FOR UPDATE SKIP LOCKED"| PG
    W -->|"fenced result/failure commit"| PG
    W -.->|"best-effort event"| REDIS
    R -->|"SKIP LOCKED expired lease scan"| PG
    R -.->|"best-effort recovery event"| REDIS

    PROM -->|"GET /metrics"| API
    PROM -->|"each replica :9101"| W
    PROM -->|":9102"| R
    API -.->|"OTLP/HTTP spans"| OTEL
    W -.->|"OTLP/HTTP spans"| OTEL
    R -.->|"OTLP/HTTP spans"| OTEL
```

实线是领域正确性所需路径，虚线是可丢失或可选的观测路径。Redis、Prometheus 和
OpenTelemetry 均不能覆盖 PostgreSQL 中的最终状态。

## Job 生命周期

```mermaid
sequenceDiagram
    participant W as Worker
    participant DB as PostgreSQL
    participant T as Target
    participant E as Evaluator
    participant R as Redis

    W->>DB: claim with SKIP LOCKED
    DB-->>W: Job + Attempt + lease/version
    loop before lease expiry
        W->>DB: heartbeat(owner, version)
        DB-->>W: new fencing version / cancellation
    end
    W->>T: target.call
    T-->>W: answer/evidence or classified error
    W->>E: evaluator.evaluate
    E-->>W: automatic metrics
    W->>DB: fenced result.persist
    DB-->>W: committed Job/Attempt/Run aggregate
    W-->>R: progress.publish (best effort)
```

Redis 箭头发生在数据库提交之后。发布失败只影响实时通知，不能回滚已经提交的
CaseResult。

## 崩溃恢复

```mermaid
stateDiagram-v2
    [*] --> Running: Worker claims
    Running --> RetryWait: transient failure or expired lease
    RetryWait --> Running: delay elapsed, new Worker claims
    Running --> Succeeded: fenced result commit
    Running --> Failed: permanent/exhausted failure
    Running --> Cancelling: cancellation observed
    Cancelling --> Cancelled: cooperative stop
```

这里是 at-least-once execution + idempotent result persistence + lease fencing，
不是 exactly-once execution。
