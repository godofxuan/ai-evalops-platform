# AI EvalOps Platform：证据化审核与改进日志

## Gate 0：冻结只读基线

### 1. Gate 范围

- 执行日期：2026-07-29（Asia/Shanghai）
- 基线提交：`a95f484d0d2e0f659a442efa5b8d4ad6ddece644`
- 基线 tree：`304e586c389c5391118714f77d95048d48d97e90`
- 基线分支：`main`
- 证据工作分支：`codex/evidence-gate-0`
- 远端：`https://github.com/godofxuan/ai-evalops-platform.git`
- 本 Gate 允许：阅读、环境采集、质量验证、真实服务连接尝试、协议草案和证据文档。
- 本 Gate 禁止：500-case 正式实验、故障注入、生产代码修改、迁移修改、push。

结构化 manifest：
[baseline-a95f484-20260729T121246Z.json](../results/gate_0/baseline-a95f484-20260729T121246Z.json)

### 2. 指令适配性判断

“先冻结基线、再决定实验与修复”适合当前项目，原因如下：

1. 当前仓库已有 235 个非集成测试、6 个真实服务合同和一次成功 CI，但没有容量曲线；
2. 现有 `run_load_test.py` 是可执行入口，不是新协议要求的重复、平衡实验；
3. 当前机器没有 Docker/PostgreSQL/Redis，直接开始 Gate 1 只会产生环境失败；
4. SSRF、跨进程 trace 和真人双评涉及产品/身份决策，不能由 Codex 单方面冻结合同；
5. 先绑定 SHA、环境与证据等级，可以防止后续把不同代码或不同机器的结果混在一起。

因此 Gate 0 没有修改生产代码，也没有把已有 CI 合同改写成容量或故障实验。

### 3. 证据等级

| 等级 | 本日志中的含义 |
|---|---|
| `VERIFIED` | 本机在本 Gate 实际运行并得到可重复结果 |
| `CONTRACT_VERIFIED` | 代码合同或绑定当前 SHA 的远端真实服务 CI 已运行，但不是容量/故障实验证据 |
| `DIRECTIONAL` | 只适合形成假设，不能用于硬性结论 |
| `NOT_RUN` | 没有执行 |
| `FAILED` | 命令实际执行并失败；必须保留失败边界 |
| `UNKNOWN` | 当前证据无法判断 |

### 4. 基线环境

| 项目 | 实际值 | 等级 |
|---|---|---|
| 操作系统 | Windows 11 专业版，10.0.26200，x64 | `VERIFIED` |
| CPU | AMD Ryzen 5 7500F，6 cores / 12 logical | `VERIFIED` |
| 内存 | 31.62 GiB；采集时可用 12.26 GiB | `VERIFIED` |
| D 盘 | 已用 713.93 GiB；可用 67.59 GiB | `VERIFIED` |
| 项目 Python | CPython 3.12.13 | `VERIFIED` |
| 系统 `python` | CPython 3.13.5 | `VERIFIED` |
| `py` 默认 | CPython 3.14 | `VERIFIED` |
| uv | 当前 shell 与常见安装位置均未找到 | `FAILED` |
| Docker / Compose | 命令不存在 | `FAILED` |
| PostgreSQL client/server | 命令不存在；5432 未监听 | `FAILED` |
| Redis client/server | 命令不存在；6379 未监听 | `FAILED` |
| uv.lock | 60 个 package entry；SHA-256 `9d44fb6...bbb9c` | `VERIFIED` |

这里的 `FAILED` 表示当前环境前置条件不满足，不表示产品合同失败。旧文档记录过 uv
0.11.32，是历史环境证据；本 Gate 不能用历史值替代当前 shell 的 `NOT_FOUND`。

### 5. 命令与结果

| 检查 | 本 Gate 结果 | 等级 |
|---|---|---|
| `git status --short --branch` | `main...origin/main`，无文件变更 | `VERIFIED` |
| Ruff format | 199 files already formatted | `VERIFIED` |
| Ruff lint | All checks passed | `VERIFIED` |
| mypy | 103 source files，无问题 | `VERIFIED` |
| 非集成 pytest | 235 passed，6 deselected，7.36s | `VERIFIED` |
| Alembic heads/history | 单一 head `20260729_0008`，8 个 revision | `VERIFIED` |
| Alembic offline SQL | exit 0，388 行，BEGIN/COMMIT 完整 | `VERIFIED` |
| `uv lock --check` | `uv` CommandNotFound | `NOT_RUN` |
| 本机真实 integration | 6 failed，235 deselected，21.95s | `FAILED` |
| Compose config/smoke | `docker` CommandNotFound | `NOT_RUN` |
| GitHub Actions Run #8 | 两个 job completed/success | `CONTRACT_VERIFIED` |

离线 SQL SHA-256：
`67f4fd99df56ad95816b09a3c72b2a222c549e070e67244aaf36a75ded4f6d1f`。
SQL 明确包含：

```sql
ALTER TABLE artifacts ALTER COLUMN artifact_type TYPE VARCHAR(32);
```

远端合同证据：
[GitHub Actions Run #8](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30425920287)
绑定同一个基线 SHA `a95f484`。它证明 CI 中的 PostgreSQL/Redis integration、migration、
Docker build 和 Compose readiness 成功；它没有执行 Gate 1–4 的正式实验。

### 6. 本机真实服务失败分析

#### 观察

显式设置 `EVALOPS_RUN_INTEGRATION=1` 后运行全部 6 个 integration contract，不再让它们
因环境开关而 skipped。

#### 结果

- PostgreSQL 路径：`psycopg.errors.ConnectionTimeout`；
- Redis 路径：`ConnectionRefusedError 10061`；
- readiness：HTTP 503；
- 汇总：6 failed，235 deselected。

#### 判断

失败发生在测试准备或依赖探测阶段，与 5432/6379 未监听一致。没有测试进入能够判断
tenant、fencing、幂等或 review 业务断言的阶段，所以：

- 当前本机执行必须保留为 `FAILED`；
- 对应产品合同在当前机器上是 `UNKNOWN`，不是“业务测试失败”；
- Run #8 可以标为 `CONTRACT_VERIFIED`，但不能覆盖本机失败；
- 不应修改测试来自动 skip，因为本次目的就是证明真实前置条件不存在。

### 7. 当前 Prometheus 与 Trace 基线

当前配置：

| 配置 | 值 |
|---|---|
| metrics | enabled |
| API | `/metrics` |
| Worker | `0.0.0.0:9101` |
| Reaper | `0.0.0.0:9102` |
| OTEL | enabled |
| service name | `ai-evalops-platform` |
| OTLP endpoint | 未配置 |

当前 13 个逻辑指标：

```text
api_request_total
api_request_duration
run_created_total
job_queue_depth
job_running
job_succeeded_total
job_failed_total
job_retry_total
job_lease_expired_total
worker_heartbeat_age
case_duration
sse_connections
redis_publish_failures_total
```

API request 只使用 method/route/status 有界标签，其余指标无 tenant/run/job/attempt
高基数标签。Prometheus client 自动生成的 `_created` series 不算额外业务指标。

对 Gate 1 而言，现有指标仍缺：

- queue wait 分布；
- claim transaction latency；
- PostgreSQL lock wait；
- API/Worker/Reaper CPU 与 RSS 时间序列；
- PostgreSQL active/idle connections 时间序列；
- 每个实验 arm 与环境/commit 的机器可读绑定。

这些缺口必须先形成实验侧采样方案或 RED contract，不能在报告中用近似值冒充。

## Gate 1 协议草案：500-case 与 Worker 扩展

状态：`DRAFT / NOT_RUN`。必须由用户确认 success/adoption gate 后才能正式运行。

### 1. 研究问题

在固定单机 Compose、固定提交、固定 500-case dataset 和确定性 MockTarget 下，Worker
从 1 扩展到 2/4/8 时：

- 吞吐如何变化；
- queue wait 与端到端延迟如何变化；
- 哪个并发度开始出现收益递减或负扩展；
- transient retry 是否改变扩展曲线；
- durable result、counter、fencing 不变量是否始终成立。

这不是生产吞吐测试，也不外推到多主机或真实模型 Target。

### 2. 正式运行前置条件

1. 独占的非生产 Docker/Compose 环境；
2. Docker、Compose、PostgreSQL、Redis 版本可采集；
3. `git status` clean，HEAD 固定；
4. Run #8 级别的质量与 integration 回归通过；
5. 数据盘至少保留 20 GiB；
6. API Key 仅存在当前 shell，不写 manifest、命令行或仓库；
7. 时间同步正常；
8. 用户确认 success/adoption gate；
9. 用户确认是否接受增加实验侧指标采样代码；
10. warm-up 未通过时不得进入正式 arm。

### 3. Dataset

- 精确生成 500 个 case，case ID 为 `load-0000` 到 `load-0499`；
- JSON 使用固定 UTF-8、紧凑分隔符和固定字段顺序；
- 保存原始 `dataset.jsonl`；
- 对原始 bytes 计算 SHA-256；
- 保存 Dataset ID、Version ID、服务端 dataset hash；
- 所有正式 arm 必须引用同一 Dataset Version；
- transient workload 通过 deterministic case metadata 定义，不能在运行时随机挑失败 case。

### 4. Workload

`io_latency_v1`：

- 全部 500 case；
- `fixed_delay_ms=25`；
- 全部首次成功；
- `max_attempts=3`。

`transient_5pct_v1`：

- 同一 Dataset Version；
- 按 `sha256(case_id)` 排序选固定 25 个 case；
- 这 25 个 case 使用 `fail_until_attempt=1`，第二次成功；
- 其余 case 首次成功；
- retry base/max/jitter 固定并进入 manifest；
- 预期 retry 数是合同输入，不是强行要求最终一定成功。

如果当前 MockTarget metadata 无法在同一不可变 Dataset 中表达这两个 workload，应先写
实验合同测试，再做最小实验工具修改；不得改变生产 Job/lease/result 语义。

### 5. Worker arm 与顺序

Worker 数：1、2、4、8。

正式重复数建议 4 次，使每个 Worker 数在每个顺序位置各出现一次：

| repetition | 顺序 |
|---|---|
| R1 | 1 → 2 → 8 → 4 |
| R2 | 2 → 4 → 1 → 8 |
| R3 | 4 → 8 → 2 → 1 |
| R4 | 8 → 1 → 4 → 2 |

两个 workload 的先后顺序在相邻 repetition 中交替。正式运行前另做 warm-up，warm-up
Run ID 与采样全部保存，但不进入正式统计。

### 6. 时间与指标定义

必须同时保存客户端单调时钟和数据库时间：

- client wall：创建请求开始到 terminal snapshot；
- run duration：`finished_at - created_at`；
- execution duration：`finished_at - started_at`；
- throughput：`terminal_jobs / execution_duration`，另保存 client-wall throughput；
- queue wait：每个 Job 的 `started_at - created_at`；
- end-to-end case latency：`finished_at - created_at`；
- Target/Evaluator latency：CaseResult/Attempt 中现有 latency；
- p50/p95/p99：type-7 线性插值，并保存原始样本；
- claim latency：claim span/实验采样器测得的领取事务耗时；当前未持久化，缺失时必须
  `UNKNOWN`；
- DB lock wait：固定频率采样 `pg_stat_activity.wait_event*` 与 `pg_locks`；未采集时
  必须 `UNKNOWN`；
- CPU/RSS：每秒采集各 API/Worker/Reaper/PostgreSQL/Redis 容器；
- PostgreSQL connections：每秒保存 active/idle/waiting；
- Redis publish failures：每个进程指标起止差值；
- retry count：Attempt 聚合；
- stale rejection：专门合同计数，不能从“没有 duplicate”倒推；
- duplicate CaseResult：按 job_id 与 run_id/case_id 两种分组检查。

### 7. 每个 arm 的 durable 验收

以下 SQL/聚合不变量任一失败，该 arm 标记 `FAILED`，仍继续保存证据：

1. Run 的 Job 总数等于 500；
2. 所有 Job 进入显式终态或有可解释的 deadline failure；
3. 每个 succeeded Job 恰好一个 CaseResult；
4. `case_results(job_id)` 无重复；
5. `case_results(run_id, case_id)` 无重复；
6. Run counters 与 Job 分组聚合一致；
7. Attempt 编号连续且不重复；
8. 没有超过协议 deadline 的无解释 running/cancelling；
9. transient workload 的 retry 数与实际 Attempt 聚合一致；
10. stale writer 测试仍拒绝旧 owner/version。

不允许因为某个 arm 失败而删除或覆盖目录。

### 8. 结果布局

```text
docs/results/load/<run_id>/
  manifest.json
  protocol.md
  dataset.jsonl
  dataset.sha256
  environment/
    host.json
    versions.json
    compose-config.txt
  raw/
    arm-order.json
    client-events.jsonl
    job-samples.jsonl
    db-samples.jsonl
    resource-samples.jsonl
    prometheus-samples.jsonl
  summary/
    arms.csv
    aggregates.json
    invariants.json
  failures/
    commands.log
    compose.log
    failed-arms.json
  plots/
    throughput.png
    latency-percentiles.png
    queue-wait.png
    cpu-rss.png
    db-connections-lock-wait.png
  README.md
```

目录必须以 create-only 方式创建。重跑使用新的 `<run_id>`。

### 9. 停止条件

- 环境或 HEAD 在实验中变化；
- dataset hash 变化；
- warm-up 不通过；
- Compose 服务非预期重启；
- 磁盘不足；
- 监测器丢失连续样本；
- 一个 arm 超过 deadline；
- durable invariant 失败。

停止不等于删除。当前 arm 和此前所有 arm 都要原样保存。

### 10. Gate 1 当前代码差距

当前 `scripts/run_load_test.py`：

- 每个 Worker 数只运行一次；
- 只有 fixed-delay workload；
- 顺序固定为 1/2/4/8；
- 没有独立 warm-up；
- 只输出 wall time、throughput、p50/p95、duplicate、retry、failure；
- `ExperimentClient.create_dataset_version()` 丢弃服务端 version hash，只返回 ID；
- 输出是单个 JSON，不是不可覆盖的证据目录；
- 没有 p99、queue wait、claim latency、lock wait、CPU/RSS、DB connections 或 Redis
  failure 差值。

因此现有脚本不能直接作为 Gate 1 正式协议执行器。下一 Gate 应先用 RED tests 固定 manifest、
目录、顺序和汇总合同，再最小扩展实验工具。

## Gate 2 协议草案：真实 Worker 强杀与 Fencing

状态：`DRAFT / NOT_RUN`。

关键原则：

1. 使用独占环境中的明确 Worker 容器 ID 做 OS 级 kill；
2. 在 kill 前保存 Job、Attempt、owner、version、heartbeat、lease expiry；
3. 用数据库状态轮询 lease 到期和 Reaper 审计，不用固定 sleep 代替协议事件；
4. 同时运行两个 Reaper，保存各自处理结果；
5. Worker B 新 claim 后，使用保存的旧 fencing token 通过受控测试驱动尝试 stale commit；
6. stale commit 必须得到明确 `LeaseLostError`，不能只看“最终没重复”；
7. 最终验证一个 durable CaseResult、唯一 Attempt 编号和正确 Run counters。

时间定义：

- detection latency：首个超过 lease expiry 的观测时间减 lease expiry；
- requeue latency：retry_wait/queued 审计时间减 lease expiry；
- new-claim latency：新 Attempt started_at 减 requeue 时间；
- completion latency：最终 CaseResult created_at 减新 Attempt started_at。

现有 failure script 使用固定 `lease_recovery_wait_seconds`，只能提供方向性演示；正式 Gate 2
需要事件驱动采集。用户必须监督 kill，并确认目标是独占开发容器。

## Gate 3 协议草案：Redis/PostgreSQL 故障矩阵

状态：`DRAFT / NOT_RUN`。

每个场景使用独立 Run、独立目录和明确的 before/injection/recovery 时间戳。

Redis：

- publish 前 stop；
- SSE 已订阅时 stop；
- restart 后新 publish；
- 验证 durable Job/Run 继续；
- 重连首帧是 PostgreSQL snapshot；
- readiness 503 策略单独记录。

PostgreSQL：

- claim 前 stop；
- Target 执行中 stop；
- result persist 前 stop；
- restart/reconciliation；
- 连接池耗尽；
- schema/head mismatch。

必须记录最终数据库事实、重复结果、错误类型、日志 reason code 和恢复后 reconciliation。
“进程仍活着”不能写成“自动恢复成功”。

## Gate 4 协议草案：30–60 分钟 Soak

状态：`DRAFT / NOT_RUN`。

- 推荐先执行 30 分钟预演，协议稳定后再执行 60 分钟正式 soak；
- 每分钟生成固定混合 workload；
- 每秒采集资源，报告按分钟聚合但保留秒级 raw；
- 保存 API/Worker/Reaper RSS、handle/thread/task、GC/CPU、DB active/idle、queue depth、
  running age、lease expiry、Redis connections、error rate 和 p95；
- 周期 Worker restart 仅在用户批准且独占环境中执行；
- 通过线性趋势、峰值、异常窗口和前后稳态比较判断泄漏，不只看最终平均；
- 任何资源单调增长结论必须带置信区间或至少保留原始序列。

## Gate 5 协议草案：HTTP Target SSRF DNS TOCTOU

状态：`BLOCKED_BY_PRODUCT_DECISION / NOT_RUN`。

正式 RED test 前必须由用户冻结：

- allowlist 管理者；
- HTTPS 是否强制；
- redirect 默认策略；
- 是否允许任意用户域名；
- 是否有部署级 egress proxy。

测试必须覆盖 DNS rebinding、302 私网跳转、混合 A/AAAA、IPv4-mapped IPv6、link-local、
metadata、IDNA/normalization 和 DNS error/timeout。当前实现每次请求前
`getaddrinfo`，但 httpx 实际连接没有绑定已验证 peer；因此当前证据只能写
“存在输入与解析防线，DNS check/connect TOCTOU 未解决”。

## Gate 6 协议草案：异步 Trace 关联

状态：`DRAFT / NOT_RUN`。

优先比较：

1. 持久化 traceparent 并继续 parent；
2. Worker/Reaper 新建 trace，使用 span link 关联 API/原 Job；
3. 只使用领域 ID 日志关联。

长时间异步任务的默认候选是 span link，避免把 API span 维持到任务终态。开始实现前应先写
contract，验证 context 不含秘密、retry attempt 可区分、Reaper link 指向原 Job context、
exporter failure 不影响业务，以及 Prometheus 没有 trace ID 标签。

## Gate 7 协议草案：RAG 真人双评 Pilot

状态：`BLOCKED_BY_HUMANS / NOT_RUN`。

Codex 只能准备：

- 固定 RAG commit/model/runtime manifest；
- immutable Dataset Version；
- 不含 machine score/model arm/另一 Reviewer 信息的 packet；
- consent 和最小身份字段清单；
- agreement/kappa/case disagreement 计算与报告模板；
- 跨两个项目的演示步骤。

Reviewer A、Reviewer B 与第三位 adjudicator 必须由用户邀请的不同真人担任。Codex 不得提交
human review，也不得根据预期结果筛选或重写人工标签。

## Gate 0 结论

### 已证明

- 基线 SHA 与工作树已冻结；
- 本机 Python 质量、类型、非集成测试和离线迁移通过；
- 当前 Prometheus 指标目录和低基数合同存在；
- 同一 SHA 的 GitHub Actions 真实服务合同与 Compose smoke 成功；
- 当前本机确实不具备运行正式 Docker 实验的基础设施。

### 未证明

- 任何 Worker 容量曲线或 p95 拐点；
- 真实进程 kill 的恢复时间；
- Redis/PostgreSQL 故障恢复矩阵；
- 30–60 分钟资源稳定性；
- 完整 SSRF 防护；
- API/Worker/Reaper 跨进程 trace 关联；
- 真人评审质量；
- exactly-once、生产容量、生产安全或灾难恢复。

### 代码与测试变更

- 生产代码：无；
- 测试：无；
- migration：无；
- CI/Compose：无；
- 文档/证据：新增本日志与 Gate 0 JSON manifest。

### Commit 范围

Gate 0 文档提交以分支范围 `a95f484..codex/evidence-gate-0` 为准。未 push。

### 下一步

停止。只有用户确认 Gate 1、定义 success/adoption gate，并提供或批准可运行的独占 Docker
环境后，才开始 Gate 1 的 RED tests 和实验工具改进。

## Gate 0 复验：gate0-20260729T200900+0800-a95f484

本节是同一基线 SHA 的第二次只读复验，保留在原 Gate 0 记录之后，不替换前一批证据。

- 基线 SHA：`a95f484d0d2e0f659a442efa5b8d4ad6ddece644`；
- 正式 500-case：未启动；
- 生产代码、测试、migration、CI/Compose 语义：未修改；
- 仓库内 uv：`.codex-tools/Scripts/uv.exe` 0.11.32，lock check 与 sync dry-run 通过；
- Ruff format/lint、mypy：`VERIFIED`；
- 默认 `.pytest-tmp`：222 passed、13 setup errors，`FAILED`；
- 新系统 basetemp：235 passed、6 deselected，`CONTRACT_VERIFIED`；
- 真实服务：5432/6379 不可达；强制 integration 连接尝试被保留为基础设施
  `FAILED`，不是 pass/skip；
- Alembic：单 head `20260729_0008`，offline SQL 完整生成，`VERIFIED`；
- Compose smoke：Docker 命令不存在，`NOT_RUN`；
- Prometheus：13 个逻辑指标与 5 个定向合同通过；live 多进程抓取 `NOT_RUN`。

复验证据：

- [manifest](../results/gate_0/gate0-20260729T200900+0800-a95f484/manifest.json)
- [raw evidence summary](../results/gate_0/gate0-20260729T200900+0800-a95f484/raw_evidence.md)
- [Gate 1 protocol draft](../results/gate_0/gate0-20260729T200900+0800-a95f484/gate_1_protocol_draft.md)

复验仍不支持容量、扩展拐点、lock-wait、强杀恢复时间、故障恢复、soak、完整 SSRF、
跨进程 trace 或真人双评结论。Gate 0 到此停止，等待用户确认。

## Gate 1 工具建设

Gate 1 已完成 prepare/preflight/reconciliation/collector/summary 的合同化实现，但当前主机
没有 Docker/PostgreSQL/Redis，正式 500-case 矩阵仍为 `NOT_RUN`，没有容量或推荐 Worker
结论。完整的逐步判断、RED→GREEN、问题与效果记录见：

- [Gate 1 execution log](../gate_1_execution_log.md)
