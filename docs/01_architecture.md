# Phase 0 架构骨架

## 1. 当前边界

第一版保持单仓库、单应用代码库、多个进程。Phase 0 只建立进程和依赖边界：

```text
Client
  |
  v
FastAPI API ---- readiness ---- PostgreSQL
     |               |
     |               +-------- Redis
     |               |
     |               +-------- artifact directory
     |               |
     |               +-------- Alembic revision
     |
     +---- structured JSON logs

Worker process ---- lifecycle scaffold only in Phase 0
Reaper process ---- lifecycle scaffold only in Phase 0
```

## 2. 组件责任

### API

- 处理 HTTP 请求；
- 生成或传播 request ID；
- 提供 liveness 和 readiness；
- 在 lifespan 中创建并关闭 PostgreSQL/Redis 客户端。

### PostgreSQL

Phase 0 只验证连接和 Alembic revision。领域表从后续阶段按学习顺序加入。

### Redis

Phase 0 只验证连接。它不是最终事实来源，也不在本阶段发布业务事件。

### Artifact 目录

Phase 0 只验证目录存在且可写。内容寻址、原子写入、跨租户访问控制属于后续阶段。

### Worker 与 Reaper

两个进程使用与 API 相同的配置和日志基础。Phase 0 入口等待停止信号并清楚记录“业务能力尚未实现”，不会访问 Job 表，也不会声称具备任务执行或恢复能力。

## 3. 为什么不在 Phase 0 创建领域表

先创建全部表会造成两个问题：

1. 数据模型在相应行为合同和测试之前被提前固化；
2. 容易误以为“表存在”等于租户隔离、并发语义和恢复机制已经成立。

因此 Phase 0 只创建 Alembic 基线。每个领域阶段再通过测试驱动加入相应表和约束。

## 4. 替代方案与本阶段未采用原因

### 用 SQLite 做本地集成测试

未采用。SQLite 不能证明 PostgreSQL 的事务、行锁、`SKIP LOCKED` 和并发唯一约束语义。

### 让 Redis 决定 readiness 之外的状态

未采用。Redis 后续只承担可丢失的实时能力；持久状态必须由 PostgreSQL 决定。

### Phase 0 就加入 Celery

未采用。Celery 会隐藏项目要亲自学习和证明的领取、租约、心跳与恢复机制。

### 一次创建未来所有模块空文件

未采用。大量空文件不提供行为或架构证据，还会增加导航成本。文件将在相应阶段按需要创建。
