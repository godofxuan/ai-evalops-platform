# 架构图

```mermaid
flowchart LR
    C["Client / CI / Experiment scripts"]
    API["FastAPI API<br/>auth · idempotency · query"]
    RELAY["API Outbox runtime<br/>relay · fenced ack · retention cleanup"]
    PG[("PostgreSQL<br/>durable state + outbox")]
    REDIS[("Redis Pub/Sub<br/>ephemeral progress")]
    ART["Content-addressed<br/>local artifacts"]
    W["Worker replicas<br/>claim · heartbeat · evaluate"]
    R["Reaper<br/>expired lease recovery"]
    SSE["SSE clients"]
    PROM["Prometheus scraper"]
    OTEL["OpenTelemetry Collector<br/>(optional, not bundled)"]

    C -->|"Bearer API key + Idempotency-Key"| API
    API -->|"Run/cancel state + outbox<br/>tenant-scoped transaction"| PG
    API --> ART
    API -->|"snapshot first"| SSE
    REDIS -->|"live events"| API
    API -->|"SSE stream"| SSE

    W -->|"claim/result/failure<br/>state + outbox"| PG
    R -->|"lease recovery + outbox<br/>ordered Run locks"| PG
    RELAY -->|"claim pending SKIP LOCKED"| PG
    RELAY -->|"Redis publish"| REDIS
    RELAY -->|"fenced ack / retry"| PG
    RELAY -->|"bounded retained delivered cleanup"| PG
    API -->|"durable backlog snapshot<br/>success time + failure count"| PG

    PROM -->|"GET /metrics"| API
    PROM -->|"each replica :9101"| W
    PROM -->|":9102"| R
    API -.->|"OTLP/HTTP spans"| OTEL
    W -.->|"OTLP/HTTP spans"| OTEL
    R -.->|"OTLP/HTTP spans"| OTEL
```

API、Outbox relay 与 retention cleanup 是同一 API 进程中的不同职责，不是额外 Compose 服务。
dispatcher 与 cleanup 使用独立 cadence 和 task；PostgreSQL 是最终状态和待发布意图的持久边界；
Redis 仍是可丢失的在线通知层。Prometheus 和 OpenTelemetry 不能覆盖 PostgreSQL 中的最终状态。
若 Outbox snapshot 失败，API 保留上次 backlog 值并暴露 last-success timestamp 与 failure Counter；
Prometheus 用 freshness 判断旧值，目标完全不可抓取仍由 `up` 告警负责。

## Job 生命周期

```mermaid
sequenceDiagram
    participant W as Worker
    participant DB as PostgreSQL
    participant T as Target
    participant E as Evaluator
    participant O as API Outbox relay
    participant R as Redis

    W->>DB: claim with SKIP LOCKED
    W->>DB: same transaction adds running event intent
    DB-->>W: committed Job + Attempt + lease/version
    loop before lease expiry
        W->>DB: heartbeat(owner, version)
        DB-->>W: new fencing version / cancellation
    end
    W->>T: target.call
    T-->>W: answer/evidence or classified error
    W->>E: evaluator.evaluate
    E-->>W: automatic metrics
    W->>DB: fenced result + Run aggregate + event intent
    DB-->>W: state and Outbox commit atomically
    O->>DB: lease pending Outbox row
    DB-->>O: stable event_id + payload
    O->>R: progress.publish
    alt publish succeeds within lease
        O->>DB: fenced mark_published
    else failure or timeout
        O->>DB: release lease + bounded retry delay
    end
```

Redis 网络调用发生在短认领事务提交之后，不持有 PostgreSQL claim lock。发布失败只影响实时
通知并留下 pending row，不能回滚已提交的 CaseResult。Redis 已接受但数据库确认前崩溃时，
租约过期后会以同一 event ID 重放，所以是 at-least-once，不是 exactly-once。

独立 cleanup task 只选择超过 retention 的 `published_at IS NOT NULL` 行，按 `published_at,id`
稳定排序、限定 batch 并 `SKIP LOCKED` 删除。pending 行不参与；migration downgrade 只能移除
查询索引，不能恢复 maintenance 已经删除的 delivered intent。

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
