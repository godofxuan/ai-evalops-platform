# P2-6 Worker 集群总资源证据改进记录

## 1. 阶段结论

- 阶段：P2-6，Worker 集群总 CPU/RSS 证据。
- 起始提交：`a325f85d1cdf407b950976bebb7ea12f46a7df9f`。
- RED 提交：`646e43b1168c6282b8a4805e9a4808cb7c99a3a0`。
- GREEN 提交：`c3128a5c0499d4e510dd7304c36a974d965daf13`。
- 当前状态：`LOCAL_CONTRACT_VERIFIED / REMOTE_CI_PENDING / FORMAL_GATE_NOT_RUN`。
- prepared manifest：schema v6。
- Gate 1 result：schema v4。
- final bundle：仍为 schema v1。
- Prometheus evidence：仍为 schema v2。
- migration：无。

本阶段修复的不是“图上换一个标题”，而是资源证据的统计单位错误。旧实现把 API、Worker、
Reaper、PostgreSQL、Redis 的样本全部压平成一个 CPU/RSS 数组；图表随后再选择单个容器峰值。
这既不是 Worker 集群总量，也不能回答“Worker 从 1 扩到 2/4/8 后，整组 Worker 消耗了多少
资源”。

最终合同是：在每一个同一时刻的 Docker stats 快照内，只对 Compose `service=worker` 的全部
副本求和，再对这些“快照总量”计算 p50/p95/p99/peak。不能把不同时间出现的每容器峰值相加，
也不能把 API 或数据库资源混入 Worker 集群数字。

## 2. 动手前判断：P2-6 是否合适

结论：合适，而且应在正式 Gate 之前完成。

判断理由：

1. P2-5 已能自动检查 expected arm 完整性，但仍把错误统计单位写进图表；如果先运行正式
   500-case/32-arm，得到的 CPU/RSS 证据将无法可靠用于人工 adoption。
2. Worker count 是实验自变量，资源曲线的被测对象应是 Worker 集群，而不是“所有容器中的
   最大单容器”。
3. P2-4 的 Compose limit 是隔离默认值，不是容量结论；P2-6 只修复测量语义，不反向宣称
   这些 limit 已调优。
4. 该改动不需要数据库 migration，也不需要改变生产任务执行语义，风险集中在实验工具和
   evidence schema 内，适合独立小阶段完成。

不合适的做法是直接运行正式 Gate 后再解释旧图。那会把已知测量缺陷带入不可覆盖 evidence，
且违背“先冻结合同、再运行实验”的顺序。

## 3. 修改前的真实数据流

旧数据流如下：

```text
docker stats snapshot
  -> API / Worker / Reaper / PostgreSQL / Redis 每容器样本
  -> 把所有 cpu_percent 压成一个数组
  -> 把所有 rss_bytes 压成一个数组
  -> summary.cpu_rss = 全部容器中的单样本 peak
  -> cpu_rss_by_container = 每个容器自己的跨时间 peak
  -> plots._point = 再取最大单容器 peak
```

主要问题：

- 非 Worker 服务被混入结果；
- 结果代表最大单容器，不代表 Worker 集群；
- 如果改成“把每容器 peak 相加”，这些 peak 可能来自不同时间，仍然不是真实快照总量；
- `docker stats` 返回值没有与 Compose service metadata 绑定，只保留了一个 container 字符串；
- 同一轮采集的多容器样本只有相同时间文本，没有明确快照序号；
- 缺少某个 Worker 副本时没有 fail-closed 的 UNKNOWN 语义；
- result schema v3 无法准确表达新的集群分布与证据状态。

## 4. 方案比较

### 4.1 方案 A：继续取最大单容器

优点是无需改代码。缺点是 Worker 数增加后，曲线仍只看最忙的一个副本，不能表示总资源成本。
拒绝。

### 4.2 方案 B：把每个容器的跨时间 peak 相加

实现简单，但统计上错误。例如 Worker A 在第 1 秒达到峰值、Worker B 在第 8 秒达到峰值，二者
相加会制造一个从未同时出现的集群峰值。拒绝。

### 4.3 方案 C：按同一快照求和，再计算分布

每次 `docker stats` 调用产生一个明确 `snapshot_index`；同一 index 内只求和 Worker 副本，
得到 CPU/RSS snapshot total，随后计算 p50/p95/p99/peak。采用。

### 4.4 Worker 身份绑定方案

未采用容器名 pattern 或 `worker-1` 字符串猜测。容器名会受 Compose project name、scale 和
运行方式影响。采用 Compose `ps --format json` 的 `ID/Name/Service` metadata，再用
`docker stats --no-trunc --format "{{json .}}"` 的完整 ID 与 Name 做唯一匹配。

Docker 官方 CLI 文档说明了 `docker stats` 的 JSON format 字段和 `--no-trunc` 选项：
[docker container stats](https://docs.docker.com/reference/cli/docker/container/stats/)。实现不信任
可能反映用户输入的 `Container` 字段，而使用完整 ID 做主绑定、Name 做二次一致性检查。

## 5. 冻结的证据合同

### 5.1 原始样本

每条 `resources.jsonl` 记录保留：

- `container_id`：Docker stats ID；
- `container`：经 Compose metadata 复核的实际 Name；
- `service`：Compose Service，不能靠名字推断；
- `snapshot_index`：同一次 Docker stats 调用的单调序号；
- `sampled_at`：采集时刻；
- `cpu_percent`、`rss_bytes`、`memory_limit_bytes` 与原始字符串。

每次快照必须覆盖 Compose 返回的全部实验容器。缺失、重复、ID 无法唯一匹配或 Name 不一致时，
整个 Docker stats 采集轮失败，写入 collector error，并增加 missed sample。

### 5.2 Worker 集群汇总

result schema v4 的 `worker_cluster_resources` 包含：

```json
{
  "status": "VERIFIED",
  "evidence": "VERIFIED",
  "reason": "worker_totals_summed_by_snapshot",
  "source": "docker_stats:compose_service=worker",
  "expected_workers": 4,
  "snapshot_count": 10,
  "complete_snapshot_count": 10,
  "worker_containers": ["..."],
  "cpu_percent": {"p50": 0, "p95": 0, "p99": 0, "peak": 0},
  "rss_bytes": {"p50": 0, "p95": 0, "p99": 0, "peak": 0}
}
```

上面的零只是字段形状示例，不是运行结果。正式实现不会在没有样本时填零。

状态规则：

- 每个快照恰有 frozen arm plan 指定数量的 Worker：`VERIFIED`；
- 快照缺 Worker 或完全没有 Worker 样本：`UNKNOWN`，所有统计值为 `null`；
- 同一快照同一 Worker 重复、数值无效、快照序号无效或出现超过预期的 Worker：`FAILED`，
  所有统计值为 `null`；
- 任一非 `VERIFIED` 状态使该 arm 的 `valid_for_capacity_comparison=false`；
- API、Reaper、PostgreSQL、Redis 样本不进入 Worker total；
- 每容器 peak 仍保留在 `cpu_rss_by_container` 作为诊断信息，并明确附带 `service`，但不再被
  图表当成集群资源值。

### 5.3 图表和 CSV

- `cpu_and_rss.png` 读取 Worker cluster CPU/RSS peak；
- plot manifest 使用 `worker_cluster_cpu_percent_peak` 和
  `worker_cluster_rss_bytes_peak`；
- `resource_containers` 只列参与 Worker 汇总的容器；
- `summary/arms.csv` 新增两个 Worker cluster peak 列；
- UNKNOWN/FAILED 保持空值，不变成 0。

## 6. TDD 过程

### 6.1 RED：先证明旧实现不满足合同

RED 提交：

```text
646e43b test(gate1): require worker cluster resource totals
```

新增合同覆盖：

1. 两个 Worker 在同一快照内先求和，并忽略 API/PostgreSQL 的夸张值；
2. 某个快照缺一个 Worker 时返回 UNKNOWN/null，而不是把缺失当 0；
3. 同一 Worker 在同一快照重复时返回 FAILED；
4. Docker parser 必须保留 `container_id`；
5. collector 必须使用 Compose service identity 和 `--no-trunc`；
6. 图表必须读取 Worker cluster total，即使诊断字段中放入误导性的 900 单容器峰值；
7. prepared/result schema 必须升级到 v6/v4，历史 v2–v5 保持只读。

RED 证据：

```text
ImportError: cannot import name 'summarize_worker_cluster_resources'
1 collection error in 0.30s
```

单独运行 collector 合同还得到两个预期失败：parser 没有 `container_id`，collector 仍先执行
`docker compose ps --quiet`，没有使用 Compose service metadata 绑定。

这些失败发生在旧能力缺失处，不依赖 Docker daemon、数据库或网络，因此是有效 RED。

### 6.2 最小 GREEN：采集身份

第一步只改 collector：

- parser 要求 ID/Name，并拒绝空身份、非有限或负 CPU；
- 从公共 `collect_compose_service_rows` 读取 ID/Name/Service；
- `docker stats` 使用 `--no-trunc`；
- ID 必须唯一匹配，Name 必须一致；
- 必须返回所有 Compose 实验容器，不能静默漏容器。

结果：

```text
20 passed in 0.32s
```

### 6.3 最小 GREEN：同快照聚合

新增纯函数 `summarize_worker_cluster_resources`。纯函数不调用 Docker，便于用确定输入验证：

- snapshot 1：80% + 10% = 90%，100 + 300 = 400 bytes；
- snapshot 2：20% + 70% = 90%，500 + 100 = 600 bytes；
- RSS 分布为 p50=500、p95=590、p99=598、peak=600；
- API/PostgreSQL 的 999 值完全不参与。

新增三项合同：

```text
3 passed, 15 deselected
```

### 6.4 接入正式数据流

随后完成：

- collector loop 给每轮 Docker stats 样本写同一个 `snapshot_index`；
- arm plan 的 `workers` 作为 `expected_workers`；
- 删除旧的全服务 flat CPU/RSS collector arrays；
- `summarize_arm` 接收 cluster evidence，并对非 VERIFIED fail-closed；
- 图表和 CSV 改读 cluster 字段；
- prepared schema v6、result schema v4；
- 更新旧 summary 单元合同，不再把 `cpu_rss` 当当前 schema 字段。

## 7. 实际遇到的问题及处理

### 7.1 大补丁上下文不匹配

第一次尝试把所有文件放进一个 `apply_patch`，补丁假设的 `summarize_arm` 参数排列与仓库实际代码
不同，工具返回 verification failure。该失败是原子的，没有留下半个实现。

处理：先用 `git status` 证明工作区仍干净，再读取真实函数签名，把修改拆成 collector、纯函数、
调用链、图表/CSV、schema 五个小补丁。效果是每个边界都能单独测试，后续没有再发生部分写入。

### 7.2 聚焦测试组合超过工具时限

把 evidence、collector、plots、prepared evidence 和 experiment scripts 一次运行时，命令在
184 秒被外层工具终止，没有 pytest 失败堆栈。这不是测试断言失败。

处理：按职责拆分，得到可审计结果：

- evidence/collector/plots：55 passed；
- prepared evidence：34 passed；
- experiment scripts：15 项分四组全部通过。

其中最后三个冻结数据集/arm order 用例单独需要约 156 秒，解释了合并命令超时原因。

### 7.3 Ruff 与 mypy 问题

首次静态检查发现：

- 两条 RED JSON fixture 超过 100 字符；
- `percentile` 要求 `list[float]`，RSS totals 是 `list[int]`；
- 动态 sample 值未经过足够显式的类型收窄；
- 汇总字典的异构值让 mypy 无法确认嵌套 `status` 可索引。

处理：拆行；RSS 只在计算 percentile 时复制为 float，peak 仍保留 int；显式排除 bool、非有限值和
负数；给 summary 添加 `dict[str, Any]` 注解。没有添加 `noqa`、`type: ignore` 或关闭 strict。

最终全仓 format check 还要求把一个两条件 `if` 机械合并为单行。使用 Ruff formatter 后重新运行
精确代码全量测试，确保格式化后的文件同样通过。

## 8. 验证结果

| 检查 | 最终结果 | 状态 |
|---|---|---|
| RED import | 聚合函数不存在，collection error | `VERIFIED_RED` |
| collector 聚焦 | 20 passed | `VERIFIED` |
| evidence/collector/plots | 55 passed | `VERIFIED` |
| prepared evidence | 34 passed | `VERIFIED` |
| experiment scripts | 15 项分组全部通过 | `VERIFIED` |
| Gate 1 相关完整集合 | 138 passed in 269.22s | `VERIFIED` |
| 最终非 integration 全量 | 469 passed，8 deselected in 291.20s | `VERIFIED` |
| `uv lock --check` | 70 packages | `VERIFIED` |
| Ruff format | 251 files already formatted | `VERIFIED` |
| Ruff lint | All checks passed | `VERIFIED` |
| strict mypy | 117 source files | `VERIFIED` |
| 本机 Docker stats/Compose | Docker CLI 不可用，本阶段未运行 | `NOT_RUN_LOCAL` |
| GitHub Actions | 等待 push 后新 run | `PENDING_REMOTE` |
| 正式 500-case/32-arm/soak | 未授权、未运行 | `NOT_RUN` |

`8 deselected` 是带 integration marker、需要真实服务的测试，不应写成通过。此前远端 CI 已能执行
真实 PostgreSQL/Redis、image 和 Compose；P2-6 精确提交仍要等待新的远端 run，不能借用旧 run
冒充当前实现证据。

## 9. schema 与旧证据影响

- prepared v6 才能执行当前源代码；v1–v5 保持只读失效；
- result v4 才表达 Worker cluster resource semantics；v1–v3 不迁移、不改写；
- final bundle v1 只描述文件布局、原子发布和 hash，语义未变，所以不升号；
- Prometheus evidence v2 描述 Prometheus 指标状态，本阶段 Docker stats 语义不改变它；
- `docs/results/` 历史 artifact 没有被修改；
- 旧 prepared bundle 的 schema 与关键脚本 SHA 均不匹配，必须从最终干净提交重新
  `--prepare-only`，禁止手工改号或重算旧目录。

## 10. 达成效果

修改前，资源图最多能回答“所有实验容器里最忙的单个容器峰值是多少”。修改后，在未来获得
授权并运行正式 Gate 时，证据能够回答：

- 每个 arm 的 Worker 集群在每个实际快照用了多少总 CPU/RSS；
- 快照总量的 p50/p95/p99/peak 是多少；
- 哪些 Worker 容器参与了证据；
- 是否有缺副本、重复副本、无效数值或采集遗漏；
- 该 arm 是否仍有资格参与容量比较。

它仍不能回答“应该部署几个 Worker”，因为用户尚未冻结 throughput、latency、DB wait、资源余量
或成本阈值；也不能证明生产环境 sizing。

## 11. 回滚方案

本阶段没有 migration。若实现出现问题：

1. 停止任何尚未授权的正式 Gate；
2. 回滚 GREEN `c3128a5`；
3. 根据是否整体撤销合同，保留或回滚 RED `646e43b`；
4. 不修改任何已存在 `docs/results/`；
5. prepared v6/result v4 bundle 不得由旧代码继续执行；
6. 从回滚后的干净 source commit 重新 prepare 新 run ID。

回滚会重新暴露单容器峰值冒充集群资源的缺陷，因此只适合作为临时恢复，不应把旧结果用于
Worker adoption。

## 12. 学习与面试表述

推荐表述：

> 我发现扩容实验把所有服务的资源样本压平，图上展示的是最大单容器，不是 Worker 集群成本。
> 我先用 RED 固定“同一快照内只求和 Compose service=worker”的合同，再用完整容器 ID 绑定
> Compose metadata，缺副本返回 UNKNOWN、重复或无效样本返回 FAILED。最后让图表、CSV 和
> quality eligibility 都读取 result schema v4 的集群证据，同时保留每容器 peak 仅供诊断。

不应表述为：

- “Worker 资源已经优化”；
- “正式容量 Gate 已通过”；
- “8 Worker 是最佳部署值”；
- “普通单元测试证明了生产 CPU/RSS”；
- “把每个容器的峰值相加就等于集群峰值”。
