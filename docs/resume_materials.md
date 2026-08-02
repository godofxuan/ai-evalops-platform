# 简历与项目展示材料

## 一句话项目描述

设计并实现多租户异步 AI EvalOps 后端，以 PostgreSQL 事务和 lease fencing 支撑
at-least-once Job 执行、崩溃恢复、幂等结果持久化、SSE 进度、Run 比较和双人盲评。

## 中文简历要点

- 基于 FastAPI、SQLAlchemy 2、PostgreSQL 和 Redis 构建多进程 AI 评测编排平台，
  将长时评测拆为一 case 一 Job 的异步执行模型。
- 使用 `FOR UPDATE SKIP LOCKED`、lease/heartbeat、owner+version fencing 与 Reaper
  实现 Worker 竞争领取、陈旧写入拒绝和崩溃后重试恢复。
- 以 `(tenant_id, Idempotency-Key)` 唯一约束和 canonical request hash 实现并发幂等
  Run 创建，区分安全重放与 key/payload 冲突。
- 将 PostgreSQL 设为最终事实来源，Redis 仅承载可丢失进度事件；SSE 重连先发送数据库
  snapshot，再订阅 Pub/Sub，并在 Redis 故障时降级轮询。
- 实现不可变 Dataset Version、SHA-256 content-addressed artifact、case keyset
  pagination、指标聚合和同/跨版本 Run diff。
- 实现双 reviewer 盲评、不可变 submission、Task 行锁和第三方 adjudication，明确
  can_review 只是管理员信任边界，不冒充真人身份认证。
- 接入 Prometheus 与 OpenTelemetry，设计低基数指标、W3C trace context、持久化 Run carrier
  与 Worker/Reaper 异步 Span Link、Redis/SSE 故障指标和可复现实验结果保存。
- 加固六服务 Compose 拓扑：显式非 root、read-only rootfs、drop ALL、no-new-privileges、
  CPU/memory/PID limit 与最小写路径，并在 CI 用 Docker inspect 验证有效 HostConfig。
- 建立 unit/API/真实 PostgreSQL/Redis/concurrency/failure-injection 四层合同；本地
  455 个非集成测试通过，远端 CI 的真实 PostgreSQL/Redis、migration、镜像与加固 Compose
  smoke 通过；正式容量 Gate 仍未执行。

最后一条必须保留“正式容量 Gate 未执行”的限定。普通 CI 合同不能替代 500-case、32-arm、
soak 或生产环境的真实数字。

## English résumé bullets

- Built a multi-tenant asynchronous AI evaluation backend with FastAPI,
  SQLAlchemy, PostgreSQL, and Redis, modeling each evaluation case as a durable
  job.
- Implemented PostgreSQL `SKIP LOCKED` claiming, leases, heartbeats, fencing
  versions, bounded retry, and Reaper-based crash recovery for at-least-once
  execution with idempotent result persistence.
- Designed concurrent Run idempotency with tenant-scoped unique constraints and
  canonical request hashes, distinguishing safe replay from conflicting reuse.
- Kept PostgreSQL as the source of truth while using Redis only for ephemeral
  progress; implemented snapshot-first SSE reconnection and PostgreSQL fallback.
- Added low-cardinality Prometheus metrics and explicit OpenTelemetry spans for
  API, claim, target, evaluator, result persistence, recovery, and SSE paths.
- Hardened all six Compose services with explicit non-root users, read-only root
  filesystems, dropped capabilities, no-new-privileges, bounded CPU/memory/PIDs,
  and CI validation of effective Docker HostConfig.
- Created reproducible worker-scaling, idempotency, fault-injection, and Run
  comparison experiments that preserve negative results instead of overwriting
  them.

不要写 “production-grade”、“exactly once”、“zero duplicates” 或未经执行的吞吐数字。

## 3 分钟项目介绍

1. **问题**：本地评测脚本遇到长耗时、限流、Worker 崩溃、重复提交和多租户隔离。
2. **核心选择**：不使用 Celery 隐藏机制；用 PostgreSQL 同时承担 durable queue 和
   最终事实来源。
3. **正确性**：短 claim 事务 + `SKIP LOCKED`；执行在事务外；heartbeat 延长 lease；
   result/failure commit 再检查 owner/version/expiry。
4. **恢复**：Reaper 回收过期 lease，旧 Worker 失去 fencing token；唯一 CaseResult
   防第二个最终结果。
5. **实时性**：提交后 best-effort Redis publish；SSE snapshot-first，所以丢事件不丢
   最终状态。
6. **可复现性**：Run 固定 Dataset hash、target/evaluator config hash/version 和 source
   commit，结果支持指标与 case-level diff。
7. **证据边界**：本地逻辑测试与远端真实服务/Compose 合同通过，但正式并发容量 Gate 尚未执行。

## 10 分钟演示路线

1. 展示架构图和 PostgreSQL/Redis 职责边界；
2. 创建 Dataset Version，解释 hash 与不可变 artifact；
3. 20 个相同 Idempotency-Key 请求，观察唯一 run ID；
4. 展示 claim SQL 的 `SKIP LOCKED` 和短事务；
5. kill Worker，等待 Reaper 回收并由新 Worker 接管；
6. 展示旧 version 提交被拒和唯一 CaseResult；
7. stop Redis，观察 Run 仍完成、SSE 转 snapshot/polling；
8. 抓取 `/metrics` 并展示 API/Worker/Reaper span；
9. 运行四 case comparison，解释 improvement/decline/failure/recovery；
10. 结束时主动展示 limitations，而不是宣称生产级。

## STAR 故事素材

### Worker 崩溃恢复

- Situation：评测调用可能持续数十秒，Worker 随时被杀。
- Task：既要允许接管，又不能让旧 Worker 晚到后覆盖新结果。
- Action：设计 lease expiry、周期 heartbeat、递增 version 和结果提交 fencing；
  Reaper 用 `SKIP LOCKED` 回收。
- Result：自动化合同验证 stale heartbeat/result 被拒和 CaseResult 唯一；真实容量实验
  仍待 Docker 环境执行。

### SSE 资源泄漏回归

- Situation：为 SSE 添加 connection Gauge 和 trace 包装后，原 subscriber close 测试
  失败。
- Task：保证观测代码不改变异步生成器资源生命周期。
- Action：定位到外层 generator 未关闭内层 generator，使用 `aclosing` 显式传播关闭，
  并保留 Gauge 回零测试。
- Result：断连时 subscription 与 Gauge 同时释放，回归合同恢复通过。

### 指标高基数控制

- Situation：tenant/run/job ID 很适合定位问题，但直接做 Prometheus label 会产生无界
  time series。
- Task：同时满足聚合监控和单次执行定位。
- Action：Prometheus 只保留 method/route/status 等有界标签；ID 放 trace/log；
  当前 Job Gauge 从 PostgreSQL 刷新。
- Result：测试显式禁止 tenant/run/job label，保持指标可聚合。

## 需要亲自讲清楚的代码

- `app/jobs/claiming.py`：锁范围、事务边界和 Attempt 创建；
- `app/jobs/results.py`：fenced update 与唯一 CaseResult；
- `app/jobs/reaper.py`：过期 lease 和两个 Reaper；
- `app/runs/idempotency.py`、`app/runs/repository.py`：hash + unique constraint；
- `app/events/sse.py`：snapshot-first、fallback 和 generator close；
- `app/observability/metrics.py`：registry 与 label 选择；
- `app/core/telemetry.py`、`app/workers/worker.py`：trace context 和业务 span；
- `docs/13_failure_injection_matrix.md`：证据等级与尚未验证的边界。
