# Phase 9 故障与并发实验矩阵

## 证据等级

- `PASS-local`：本机已真实执行并通过；
- `CONTRACT-pass`：SQL/纯逻辑/假依赖合同已执行，但不是外部服务实测；
- `SKIPPED-no-infra`：测试存在，本机因真实基础设施缺失跳过；
- `NOT-RUN`：实验脚本存在，但本机未执行。

## 故障矩阵

| 故障 | 注入方式 | 必须保持的不变量 | 当前证据 |
|---|---|---|---|
| Worker claim 后崩溃 | Compose kill Worker，等待 lease + Reaper | 过期 Attempt 记录为 lease_expired；新 Worker 接管；旧 Worker 不能写 | `NOT-RUN`；脚本 + 真实 PG concurrency 合同 |
| heartbeat 停止 | 让 lease 过期 | Reaper 转 retry_wait/failed/cancelled；不重复回收 | `SKIPPED-no-infra`；2 Reaper 合同 |
| Target timeout | MockTarget timeout | 分类 retryable；不绕过 max_attempts | `CONTRACT-pass` |
| Target 429/500 | MockTarget HTTP fault | 分类 retryable；保存安全 error code | `CONTRACT-pass` |
| permanent failure | MockTarget permanent_failure | 不重试；Job/Run 正确聚合 | `CONTRACT-pass` |
| Redis publish 失败 | Flapping publisher + 真实 PG/Redis relay | PostgreSQL 状态不回滚；Outbox 保持 pending；有界退避后同 ID 重试 | local contract + GitHub Actions #28 integration `PASS` |
| PostgreSQL 单轮断开 | Worker fake 抛 ConnectionError | loop 记录错误并继续；不把未知结果写成成功 | `CONTRACT-pass` |
| Outbox 指标 snapshot 失败 | Job snapshot 成功、Outbox session 抛 RuntimeError | `/metrics` 仍 200；保留上次成功时间；失败 Counter +1 | local API `PASS` + GitHub Actions #34 |
| PostgreSQL 容器中断 | Compose stop postgres | liveness 仍 200；readiness 503；恢复后重新可用 | `NOT-RUN` |
| artifact 发布失败 | monkeypatch 原子 publish | 清理临时文件；不留下成功 metadata | `PASS-local`（既有测试） |
| API 响应前客户端断开 | 已提交事务与 HTTP 生命周期分离 | 已提交 Run 依赖 Idempotency-Key 重放，不重复创建 | 真实 PG 合同存在；本机 `SKIPPED-no-infra` |
| SSE 客户端断开 | 提前关闭 async generator | subscriber 关闭；连接 Gauge 回零 | `PASS-local` |
| SSE Redis 断开 | subscriber 抛 ConnectionError | 先有 PG snapshot；随后 PG polling；Run 不失败 | `PASS-local` |
| Job 成功但发布失败 | Outbox publisher 返回 false/抛异常 | CaseResult/Job 与通知意图同事务保留；relay 后续重试 | local contract + GitHub Actions #28 integration `PASS` |
| Outbox cleanup 数据库单轮失败 | maintenance fake 首轮 ConnectionError | 只记录异常类型；task 不退出；下一轮继续 | `CONTRACT-pass` |
| running 中途取消 | heartbeat 观察 cancellation | cooperative stop；旧 lease 不能继续写 | `PASS-local` unit；真实 `NOT-RUN` |

## 并发矩阵

| 场景 | 合同 | 当前状态 |
|---|---|---|
| 20 个相同 Idempotency-Key 请求 | 全部 202、同一 run ID、无 500、只创建一组 Jobs | 真实 PG 测试已扩展；本机 skipped |
| 10 Worker 竞争 100 Jobs | 100 个唯一 claim、100 个唯一 Attempt | 真实 PG 测试已扩展；本机 skipped |
| 2 Reaper 回收 99 个剩余 lease | 每个 Job 只被一个 Reaper 回收；先按序锁 Run、后插 Outbox | GitHub Actions #28 真实 PG passed；本机 skipped |
| 2 Outbox relay 竞争同一事件 | 合计一个 claim/publish；`SKIP LOCKED` 不重复持有 | GitHub Actions #28 真实 PG/Redis passed；本机 skipped |
| publish 成功、ack 前崩溃 | lease 过期后以相同 event ID 重放并 fenced ack | GitHub Actions #28 真实 PG/Redis passed；明确 at-least-once |
| 2 Outbox cleanup、batch=1 | 两条过期 delivered 各删一次；近期 delivered 与旧 pending 保留 | GitHub Actions #31 真实 PG passed；本机 skipped |
| stale heartbeat | owner/version 不匹配都拒绝 | 真实 PG 测试存在；本机 skipped |
| stale result writer | 第二次/旧 lease commit 拒绝；CaseResult 数为 1 | 真实 PG 测试存在；本机 skipped |
| cancel/result race | 最终状态必须是显式状态机允许的终态，只产生一个 CaseResult | 真实 PG 并发合同已编码；本机 skipped |

## 实验验收规则

1. 结果文件必须包含输入规模、Worker 数、时间戳和 run ID；
2. 不得只报告最好的一次；
3. 失败和部分完成结果也要保留；
4. duplicate count 必须基于结果明细计算，不接受日志目测；
5. skipped 不算 passed；
6. 脚本能够启动不算容量实验完成；
7. 任何性能结论必须注明 CPU、内存、PostgreSQL/Redis 版本和部署方式；
8. DB lock wait 尚未自动采集，执行正式实验时需要同时保存
   `pg_stat_activity`/`pg_locks` 观察结果。
