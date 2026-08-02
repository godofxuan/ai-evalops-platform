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

### 2026-08-02 P1-6 更新

上述 `BLOCKED_BY_PRODUCT_DECISION` 是审计当时的历史状态。用户随后冻结了合同：Registry 由
operator 管理、tenant 只提交 `target_id`、强制 HTTPS 443、不跟随重定向、全部 A/AAAA 必须
是原生公网地址、连接经过验证的数值 IP、保留原 Host/TLS SNI，并在读取正文前校验实际 peer。

本轮已按该合同完成应用层实现和单元/依赖边界证据，详细 RED/GREEN 过程见
[`p1_6_http_target_security_log.md`](p1_6_http_target_security_log.md)，实现提交为
`049e59e0760a50377e0cb8b53c61d166ee7dc224`，IDNA 边界跟进为
`102cb4eda90a8a79ab66d9974b62369dec418e3e`，Pytest 临时仓库隔离跟进为
`03d4832c67a3dcf4fc142363e445a5f535adbd73`。正式 Gate 5、真实网络攻击
环境、部署级 egress policy 和第三方渗透测试仍为 `NOT_RUN`，所以结论只能是“旧的二次 DNS
解析窗口已在当前 HTTPX/HTTPCore 合同下关闭”，不能写成“完整 SSRF 防护已验证”。

Pytest 隔离修复推送后的 GitHub CI Run #11（`30713653240`）两个 job 均成功，包括 migration、
6 个真实服务合同和 image build；这仍是普通 CI 证据，不是正式 Gate 5 或 SSRF 渗透结论。

## P1-7 更新：Artifact 内容去重与所有权分离

状态：`LOCAL_AND_REMOTE_CONTRACT_VERIFIED / FORMAL_GATE_NOT_RUN`。

旧 `artifacts` 表把 blob SHA/path/size 与 tenant/Run owner 放在一行，且唯一键不含 Run；同一
tenant 的两个 Run 若得到相同 type/SHA，第二个 Run 不能创建自己的 reference。实现提交
`de1a44b659ea1edc88d97ab7aec0eccb41868240` 新增：

- `artifact_blobs`：全局 content-addressed 物理事实；
- `artifact_references`：tenant、精确可选 Run、类型和 media type；
- `20260802_0009`：冲突保护、UUID 保留 backfill、Dataset FK 切换和有损 downgrade guard；
- tenant/reference/Run scoped read/delete、最后 reference 清理和已知 orphan 维护路径；
- 真实 PostgreSQL 同 tenant 双 Run、跨 tenant、并发同 SHA、缺文件与 rollback orphan 合同。

最新本地非 integration 为 424 passed、7 deselected；Ruff、mypy 115 files、uv lock、offline
migration 和 diff check 通过。真实 PostgreSQL 测试在本机明确 skipped，等待 GitHub CI，不能
提前写成通过。完整过程见
[`p1_7_artifact_ownership_log.md`](p1_7_artifact_ownership_log.md)。本修改不运行或覆盖正式
Gate 1 artifact；多主机文件生命周期和跨系统原子删除仍未解决。

后续远端证据已经产生：绑定 head `47e844a2b3bbb3c0b51fc3db20012fee3256dbdb` 的
[GitHub Actions Run #13](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30728407695)
为 success。两个 job 均成功，新增真实 PostgreSQL artifact ownership step、migration、全部
既有 integration、image build 和 Compose readiness 都明确执行。这解决了上段的远端 pending，
但不把普通 CI 改写为正式 Gate、破坏性实验或多主机一致性证明。

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

Gate 1 已完成 prepare/preflight/reconciliation/collector/summary/plot 的合同化实现。
绘图工具会以 create-new 方式同时生成五张 PNG 和机器可审计 manifest，但当前主机没有
Docker/PostgreSQL/Redis，正式 500-case 矩阵及正式数据图仍为 `NOT_RUN`，没有容量或推荐
Worker 结论。完整的逐步判断、RED→GREEN、问题与效果记录见：

- [Gate 1 execution log](../gate_1_execution_log.md)

## P2-1 更新：跨表 tenant 与 Job/Run 一致性

状态：`LOCAL_AND_REMOTE_CONTRACT_VERIFIED / FORMAL_GATE_NOT_RUN`。

审计确认正常服务路径大多从 principal 派生 tenant，但旧数据库只用单列 FK，仍允许
Dataset、Artifact、Run、API Key 与人工复核记录分别存在却来自不同 tenant，也允许 Case
Result/Review Task 的 Job 和 Run 不同源。新增 migration `20260802_0010`：

- 给 Dataset Version 增加从 Dataset 回填的 tenant；
- 用 tenant 复合 FK 绑定 Dataset/Artifact/Version/Run/API Key/Review lineage；
- 用 `(job_id, run_id)` 绑定 Result/Review Task 的 Job/Run lineage；
- upgrade 对历史矛盾失败关闭，downgrade 恢复旧 FK 和可派生列；
- CI 增加 13 类真实 PostgreSQL 非法插入与 `0010→0009→0010` round-trip。

本地 `429 passed, 8 deselected`，Ruff 241 files、mypy 116 source files、70-package lock 与
4 个离线 migration 合同均通过；真实 PostgreSQL 测试本机明确 skipped，远端结果不能提前
写成成功。完整适用性判断、RED/GREEN、63 字符 constraint 名问题、uv cache 问题和残余
边界见 [`p2_1_cross_table_tenant_consistency_log.md`](p2_1_cross_table_tenant_consistency_log.md)。

远端 head `87d85d0906ba3c42e2caf5185d5b034a6cd5f322` 的
[GitHub Actions Run #15](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30729735398)
最终为 success；两个 job、新 PostgreSQL constraint step、实际 migration downgrade/re-upgrade、
全部既有 integration、image build 与 Compose readiness 都成功。该证据只提升普通 CI 合同，
不改变正式 Gate 的 `NOT_RUN`。

## P2-2 更新：Human Review Task 创建权限

状态：`LOCAL_AND_REMOTE_CONTRACT_VERIFIED / FORMAL_GATE_NOT_RUN`。

审计确认旧 `POST /runs/{run_id}/review-tasks` 只校验 Run tenant，没有能力检查；任何同 tenant
有效 key 都能扩大 review cohort 并触发 packet artifact。直接复用 `can_review` 会让每个
reviewer 都能扩大样本，并破坏现有 creator/reviewer/adjudicator 职责分离，因此实现提交
`7aab279cdb95a2e1a615d6c982ffddee333db240` 新增独立、默认关闭的
`can_create_review_tasks`：

- migration `20260802_0011` 给所有旧 key 默认回填 false，不从历史或 `can_review` 推导；
- API Key ORM → Candidate → Principal 全链路只传播服务端数据库值；
- service 在数据库与 artifact I/O 前检查，使用独立异常与 403 code；
- CLI 用 `--review-task-creator` 显式授权，且不自动授予 reviewer 权；
- 真实 PostgreSQL 合同覆盖 ordinary/reviewer-only 拒绝且零 Task/packet 副作用、creator-only
  创建成功但 submit 被拒绝；
- API 回归证明 body/query/header 同名伪造值不能覆盖认证 Principal。

本地结果为 `435 passed, 8 deselected`；权限定向 31 passed，真实 PostgreSQL 1 skipped；
Ruff 244 files、mypy 108 source files、70-package lock、唯一 Alembic head `0011` 与 6 个离线
migration tests 全部通过。远端真实服务与 Compose 尚未执行，不能提前记 success。完整
RED/GREEN、为什么不用 `can_review`、lint 跟进、升级兼容性和回滚顺序见
[`p2_2_review_task_creation_permission_log.md`](p2_2_review_task_creation_permission_log.md)。

该修改仍不是通用 RBAC、自然人认证、组织审批或数据库 RLS；管理员必须轮换/创建新 creator
credential。正式 500-case/32-arm Gate 未启动，普通权限 CI 不改变其 `NOT_RUN`。

后续远端证据已产生：绑定 head `bbbf7a3995e770724ef79d715370ed9d771f38ca` 的
[GitHub Actions Run #17](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30730652470)
最终为 success。`quality-and-integration` 与 `compose-smoke` 均成功，且 step 级结果确认真实
Human Review、migration downgrade/re-upgrade、image、Compose migration 与 readiness 都
实际执行。这解决了本节的远端 pending，但仍不支持形式化 Gate、通用 RBAC 或生产安全结论。

## P2-3 更新：API → Worker/Reaper 异步 Span Link

状态：`REMOTE_CI_VERIFIED / FORMAL_GATE_NOT_RUN`。

审计确认 API middleware 能延续入站 W3C context，但 Run transaction 不保存来源；Worker 每次
attempt 与 Reaper 都创建新 trace，只能靠领域 ID 人工关联。直接继续 API parent 会把长时间
排队、fan-out 和 retry 合并成超大 trace，因此实现提交
`c1cd6074463a6820fa1a7cb8d12f620eb3a4a1a3` 选择异步 Span Link：

- Run 新增 nullable `origin_traceparent`，只保存首次平台 `run.create` span carrier；
- idempotent replay 不捕获或覆盖新 context，历史 Run 不伪造 backfill；
- claim/reaper 通过现有 joined Run 传播，Worker attempt 和逐 Job recovery 分别建立 linked root；
- API 来源 span、Worker/Reaper span 都携带 run/job/attempt 等领域 attributes；
- baggage/tracestate/凭据不保存，trace 不参与 tenant、授权、调度、retry 或幂等；
- malformed、disabled 和 propagator exception 安全降级为无 Link；
- migration `0012` upgrade/downgrade 只增删 nullable 55 字符列。

本地最终为 `446 passed, 8 deselected`；聚焦 59 passed、真实 PostgreSQL 1 skipped；Ruff 247
files、mypy 116 source files、70-package lock、唯一 head `0012` 与 8 migration tests 全部通过。
完整过程见
[`p2_3_async_trace_link_log.md`](p2_3_async_trace_link_log.md)。

后续远端证据已产生：绑定 head `5c5d199b1f639826c60406626e8a04223803ffe1` 的
[GitHub Actions Run #19](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30732220588)
最终为 `success`。两个 job 均成功，步骤级结果确认真实 PostgreSQL claim/reap trace
propagation、`0012` migration、P2 downgrade/re-upgrade、image build、Compose migration、
API/Worker/Reaper 启动与 readiness 均实际执行。这解决了 P2-3 的远端 pending。

没有 Collector/trace backend，所以不能声称 Link UI、采样、保留或生产 OTLP 已验证；API 与
Worker 按设计不是同一 trace。旧 prepared bundle 因 source/migration 变化必须重新 prepare，
正式 500-case/32-arm Gate 继续 `NOT_RUN`。

## P2-4 更新：Compose 运行时边界加固

状态：`REMOTE_CI_VERIFIED / FORMAL_GATE_NOT_RUN`。

审计确认应用 `Dockerfile` 虽已有 UID/GID 10001，但 Compose 六个服务没有显式锁定 user、
read-only rootfs、capability、no-new-privileges 或资源上限；migrate/Reaper 还继承了不需要的
artifact 写 volume。实现提交 `6c84cd92257e5cbe7c4722e37c1acdfe7a9fa5fa`：

- application roles 显式 `10001:10001`，PostgreSQL/Redis 使用官方 named user；
- 六服务 read-only、drop ALL、no-new-privileges，设置可配置 CPU/memory/PID limit；
- 用 tmpfs 开放 `/tmp` 与 PostgreSQL socket，只保留各角色必要命名 volume；
- 新增 fail-closed inspect verifier，并在 Compose CI 对五个常驻容器验证有效 HostConfig。

本地 RED 依次复现静态配置缺失、校验器不存在和 CI step 不存在；最终聚焦 10 passed、Gate 相关
60 passed、全量 `455 passed, 8 deselected`，Ruff 249 files、mypy 117 source files、70-package
lock 全通过。首轮 60 项命令不是断言失败，而是 180 秒外层 timeout；保持测试集合并提高工具
上限后 219.95 秒通过。额外将 unit YAML test 纳入 mypy 暴露缺少 `types-PyYAML`，正式 CI 范围
从未包含 unit tests，因此没有为超范围命令新增依赖或降低规则。

绑定实现 head 的
[GitHub Actions Run #21](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30733050517)
最终 success。fresh-volume PostgreSQL/Redis、migration、API/Worker/Reaper、readiness、Docker
inspect hardening、真实 integration、P2 migration round-trip 和 image build 均实际成功。完整过程
见 [`p2_4_compose_hardening_log.md`](p2_4_compose_hardening_log.md)。

默认限额仍不是生产 sizing；没有 rootless/user namespace/seccomp/AppArmor/NetworkPolicy/宿主机
安全证明。Compose/source hash 改变使旧 prepared bundle 失效，正式 Gate 继续 `NOT_RUN`。

## P2-5 更新：Gate 1 quality/adoption flags 自动检查

状态：`LOCAL_AND_REMOTE_VERIFIED / FORMAL_GATE_NOT_RUN`。

审计确认两个 `--confirm-*` 开关只是内容为空的用户授权 Boolean；prepared manifest 没有冻结
quality policy，aggregate 也只汇总当前存在的 summaries。它无法自动区分完整有效、已知无效和
缺失 arm，且 Boolean 容易被误读成正式 gate 结果。

RED 提交 `a9a1324` 先要求完整/缺失/无效/重复/unexpected arm、负扩展不自动采纳、policy
篡改和 schema 升级合同。GREEN 提交 `3ee4480`：

- prepared manifest v5 冻结 result schema v3、quality policy v1 和 human-owned adoption；
- expected arm plan 显式进入 finalizer，省略计划的兼容回退被移除；
- quality 自动给出 `VERIFIED`、`FAILED`、`UNKNOWN` 及 missing/invalid arm IDs；
- adoption 始终 `NOT_RUN`，仅在 quality VERIFIED 时标记可进入人工评审；
- 不自动选择 Worker，不改部署，不把负扩展删掉或当成实验基础设施失败；
- final-bundle v1 与 Prometheus evidence v2 因各自语义未变而不无意义升号。

本地最终为 `463 passed, 8 deselected`；Gate 1 相关 132 passed、finalization 收紧 16 passed；
Ruff 250 files、mypy 117 source files、70-package lock 全通过。首轮完整 Gate 回归的 3 个失败是
测试仍期待 prepared schema 4；更新为 5 并补齐 v2/v3/v4 历史只读覆盖后通过。完整记录见
[`p2_5_gate_automation_log.md`](p2_5_gate_automation_log.md)。

没有 migration，没有运行正式 500-case/32-arm，也没有用户数值 performance policy。因此没有
吞吐、p95/p99、容量拐点或部署 Worker 数结论；本机未运行真实服务/image/Compose，远端证据见
下文。

后续远端证据已产生：绑定 head `fa526f7ad6ada27ba5f9e6492afb5a8ab368b5a6` 的
[GitHub Actions Run #23](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30734753325)
最终 success。两个 job 均成功，步骤级结果确认静态质量、非 integration、全部真实服务
integration、P2 migration round-trip、application image、完整 Compose topology、readiness 和
hardening inspect 实际执行。该普通 CI 不包含正式 500-case/32-arm，adoption 继续 `NOT_RUN`。

## P2-6 更新：Worker 集群总资源证据

状态：`LOCAL_AND_REMOTE_VERIFIED / FORMAL_GATE_NOT_RUN`。

审计确认旧 Gate 1 把五类服务的 Docker stats 压平成通用 CPU/RSS 数组，图表再取最大单容器
peak。该值既混入非 Worker 服务，也不是 Worker 集群总成本；把每容器跨时间 peak 相加仍会
制造从未同时发生的假峰值。

RED 提交 `646e43b` 要求同快照 Worker 求和、缺副本 UNKNOWN、重复副本 FAILED、Compose service
绑定、图表只读 cluster total 以及 schema v6/v4。GREEN 提交 `c3128a5`：

- 用完整 Docker ID 与 Name 唯一绑定 Compose ID/Name/Service，并要求快照覆盖全部实验容器；
- collector 给同一次 stats 调用的所有行写同一个单调 `snapshot_index`；
- 只在同一快照内求和 `service=worker` 的 CPU/RSS，再计算 p50/p95/p99/peak；
- 缺副本保持 UNKNOWN/null，重复、无效、超预期保持 FAILED/null；
- 非 VERIFIED 资源证据使 arm 的容量比较资格失效；
- 每容器 peak 只保留诊断用途，图表 manifest 与 CSV 改用 Worker cluster peak；
- prepared/result 分别升为 v6/v4，final bundle v1 和 Prometheus evidence v2 不变。

本地最终 Gate 1 相关 138 passed；非 integration 全量 `469 passed, 8 deselected`；Ruff 251
files、mypy 117 source files、70-package lock 全通过。组合聚焦命令曾在 184 秒被外层工具终止，
拆分后 55、34 和 15 项分别确认全绿；静态检查发现的长行、RSS percentile 类型和动态值收窄
问题均被显式修正。完整记录见
[`p2_6_worker_cluster_resources_log.md`](p2_6_worker_cluster_resources_log.md)。

本项没有 migration，也没有修改历史 `docs/results/`。prepared v1–v5 与 result v1–v3 保持
只读，旧 bundle 必须从最终干净提交重新 prepare。本机真实 Docker 未运行。绑定 head
`4ad310a66b226122515be9683fe60ae3c1a183d2` 的
[GitHub Actions Run #25](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30737106451)
最终 success；步骤级结果确认真实 PostgreSQL/Redis、全部 integration、P2 migration
round-trip、image build、Compose migration/readiness/hardening 实际执行。正式 500-case/32-arm、
资源曲线、容量 knee 和 adoption 均未运行或得出。

## P2-7 更新：PostgreSQL transactional outbox

状态：`LOCAL_AND_REMOTE_VERIFIED / FORMAL_GATE_NOT_RUN`。

审计确认旧状态事务与 Redis publish 是不可原子双写：数据库已提交后进程退出会永久丢失通知
意图。实现新增 migration `0013` 和 tenant/run 复合 FK Outbox；Claim、成功、失败、重试、
Reaper、取消都在原事务写通知，API relay 用 `SKIP LOCKED` 租约、事务外 publish、fenced ack 与
有界退避。Worker/Reaper/cancel route 不再直发；真实 `progress.publish` span 迁移到 API relay。

真实集成覆盖事务 rollback、跨 tenant FK、两个 relay 仅一个认领、publish failure 后持久重试、
publish-before-ack crash 后同 event ID 重放。语义明确为 at-least-once；SSE 仍以 PostgreSQL
snapshot 恢复，Pub/Sub 不是历史日志。

首轮远端 #27 的 Outbox step 成功，但双 Reaper 旧测试发现新增外键锁升级死锁。根因是两个事务
先插 Outbox 获得同一 Run key-share，再都升级 `FOR UPDATE`；修复为先按固定 Run ID 顺序聚合/
锁父行，再插 Outbox。#28 两个 job 最终 success，真实并发、Outbox、migration、image、Compose
全部通过。完整提交链、RED/GREEN、工具误用/超时、锁图、部署回滚与残余 GC/metrics 风险见
[`p2_7_transactional_outbox_log.md`](p2_7_transactional_outbox_log.md)。

随后补齐 relay tracing 与文档，绑定 head `5092f49eccc504b3d13a960e872305eb08c010b9` 的
[GitHub Actions #29](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30739846288)
再次两个 job success；这次结果覆盖最终 P2-7 代码、迁移、测试和首版证据文档。

最终本地全量 `488 passed, 9 deselected`，Ruff/lint、119-source strict mypy、70-package lock
通过；真实服务本机 skipped。正式 Gate、容量、exactly-once、客户端历史回放和生产认证均未
宣称完成。

## P2-8 更新：Outbox retention 与运维可观测性

状态：`LOCAL_AND_REMOTE_VERIFIED / ALERT_RUNTIME_NOT_RUN / FORMAL_GATE_NOT_RUN`。

审计确认 P2-7 delivered 行永久保留，pending/oldest age、retry/lease-lost/cleanup 指标和告警规则
均不存在；Compose 也未转发已记录在 `.env.example` 的 dispatcher 参数。P2-8 采用 API 内独立
maintenance，而不是在 `/metrics` 产生删除副作用、耦合 dispatcher cadence 或增加独立服务。

实现只删除超过 retention 的已发布行：候选 CTE 稳定排序、限定 batch、`SKIP LOCKED`，再
`DELETE RETURNING`；pending 和业务状态不进入候选。新 `0014` partial index 与 ORM metadata
一致，downgrade 只删索引。API `/metrics` 从 PostgreSQL 刷新全局 pending/oldest age，dispatcher
与 cleanup 写无 ID Counter；九个 Outbox 参数进入 Compose；两条 Prometheus rules 作为未部署模板。

真实 PostgreSQL integration 用两个 cleanup、batch=1 删除两条 8 天 delivered，同时保留近期
delivered 与旧 pending，并得到 pending=1、oldest=691200 秒。绑定 head `69cba41` 的
[GitHub Actions #31](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30759184986)
两个 job success，覆盖全部 integration、migration、image 和 Compose。本地 `504 passed,
9 deselected`，260-file Ruff、119-source mypy、70-package lock 全通过；本地 integration skipped。
代码与首版证据文档 head `5b374d2` 又由
[GitHub Actions #32](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30759680786)
完成两个 job，证明记录阶段没有破坏同一套验证链。

一次 RED 提交前 Ruff format 非零，但 PowerShell 未自动停止后续原生命令；下一 GREEN 修正，
之后显式检查每个 `$LASTEXITCODE`。告警真实评估、dead-letter/replay 权限、Gauge freshness、大型表
在线建索引、cleanup 容量、归档/合规、soak 和正式 Gate 仍未完成。详细记录见
[`p2_8_outbox_operations_log.md`](p2_8_outbox_operations_log.md)。
