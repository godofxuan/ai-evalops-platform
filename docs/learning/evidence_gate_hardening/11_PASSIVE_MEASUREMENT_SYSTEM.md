# 被动 PostgreSQL 测量系统：为什么我们主动拒绝了自己的仪器

这不是一篇泛泛的性能测试教程，而是 AI EvalOps Platform 在真实证据上的复盘。最终实验是
GitHub Actions `31421039618`，冻结工作负载为 q1000、20:1 倾斜、8 Workers、batch 1、每次测量
100 Jobs，顺序严格为 A: OFF/ON/ON/OFF，B: ON/OFF/OFF/ON。

最终事实是：吞吐中位数扰动 -0.429156%，通过 5% 门槛；claim p95 中位数从 708.689593 ms
变为 509.975702 ms，相对变化 -28.039623%，绝对扰动 28.039623%，超过 10%。所以结果是：

```text
MEASUREMENT_SYSTEM_INVALID
PERFORMANCE_ATTRIBUTION_STOPPED_BY_MEASUREMENT_VALIDITY
```

## 1. 为什么测量系统本身也要 qualification

测量工具不是透明玻璃。它会消耗 CPU、数据库连接、锁管理器访问、缓存和 I/O，还可能改变线程或
事务的交错顺序。若直接拿一个未经验证的 observer 去解释 scheduler，就会把“被观察时出现的现象”
误当成“未观察时原本就存在的原因”。因此本项目先验证仪器是否足够低扰动，再谈因果归因。

本轮的成功标准不是把结果跑成绿色，而是让仪器接受和 scheduler 一样严格的 evidence gate。

## 2. observer effect 是什么

Observer effect 指观察动作改变被观察系统。在本项目的高竞争 claim 路径里，即使只多一次时钟读取、
Python callback、列表追加或数据库查询，也可能让两个 Worker 到达锁点的先后顺序互换。p95 是尾部
指标，对这种交错尤其敏感。

历史两次同步 observer 的 claim-p95 绝对变化分别为 11.3194% 和 13.4906%，都超过 10%。本次把
采集搬到外部进程后，变化仍达到 28.039623%。这说明“代码看起来轻量”不等于“对并发时序透明”。

## 3. 为什么“ON 更快”也属于 measurement perturbation

本次 ON 的 claim p95 比 OFF 低约 198.714 ms。直觉可能说“没有开销，反而优化了”。这是错误的
因果跳跃：采集器的目标不是优化 scheduler，而是无显著扰动地观察它。若一开仪器，尾延迟就变化
28%，不论方向为何，都说明 ON 与 OFF 不再是可直接比较的同一系统。

更快可能来自时序重排、缓存状态、数据库后台活动或自然方差。没有独立因果实验，不能选一个喜欢的
解释。

## 4. 为什么使用 absolute threshold

冻结公式是 `abs((ON median - OFF median) / OFF median)`。使用绝对值可以阻止一种危险的事后规则：
“变慢算扰动，变快算收益”。仪器如果显著加快系统，同样改变了目标变量，同样没有资格做中性观察。

本轮 throughput 的绝对扰动 0.429156% <= 5%，但 claim p95 的绝对扰动 28.039623% > 10%。两个
强制条件必须同时成立，所以整体失败。

## 5. 为什么 local recorder microbenchmark 不能证明 remote validity

历史同步 recorder 的本地微基准从约 4.93 微秒降到 3.38 微秒，只能说明单次 Python 记录路径更快。
它没有真实 PostgreSQL 锁竞争、8 个 Worker 的进程调度、容器资源争用和尾延迟分布。因此这个数字
只能标为 `LOCAL_MICROBENCHMARK_ONLY`，不能写成“生产开销降低 31%”。

同理，本机 1/5/10/20 Hz 频率研究只比较投影和 JSONL 写入路径。本机没有 PostgreSQL、Docker 或
psql，真实查询开销是 `NOT_RUN_NO_LOCAL_POSTGRESQL`。它帮助选择 5 Hz，但不能代替远程 OFF/ON。

## 6. synchronous callback 为什么特别危险

同步 callback 位于 claim transaction 的关键路径。Worker 每完成一个阶段就调用 Python 记录器，
因此额外工作与锁持有、重试和提交顺序紧密耦合。微秒级动作也可能移动锁释放时间，改变另一个
Worker 是成功 claim、等待还是 SKIP LOCKED miss。

被动方案删除了这条直接耦合：Worker 不调用 collector，collector 也不进入 Job transaction。但
“耦合更弱”只是设计事实，不等于已经通过有效性验证。

## 7. passive PostgreSQL sampling 与 in-transaction callback 的区别

被动方案运行在独立 OS 进程和独立 psycopg 连接中，以 5 Hz 只读查询 PostgreSQL 核心视图。它不修改
`claiming.py` 的生产决策流，不注入 transaction callback，不取消 backend，不改锁，不在测量期间
执行 VACUUM/ANALYZE。

区别在于影响从“每次 claim 内同步执行”变为“数据库外部定期读取共享统计/锁状态”。影响通常更弱，
但查询仍使用数据库资源，所以仍必须 qualification。本轮就是这一步没有通过。

## 8. pg_stat_activity / pg_locks 能证明什么

它们能提供 `OBSERVED` 事实：采样时某 backend 的 state、wait_event_type、wait_event，以及锁的类型、
模式、是否 granted 和安全的 relation identity。本轮四个 ON 运行得到 69 个成功样本，其中 65 个样本
观察到等待状态，公开投影共 5,393 行。

这些数据证明 collector 确实看到了采样时刻存在的等待和锁状态，也证明敏感原始 SQL 不必进入公开
仓库。

## 9. 它们不能证明什么

它们不能证明某类锁是吞吐负扩展的根因，不能证明一个 wait 导致某个 Job 的 p95，也不能证明没有被
采到的短 wait 不重要。`pg_stat_activity` 的 state 与 wait 是瞬时快照，`pg_locks` 是当时锁表状态，
不是完整的因果事件链。

所以 H1 SchedulerCoordination、H2 Tenant permit、H3 SKIP LOCKED/retry 在本轮全部是 `NOT_RUN`，
不能因为看到了 transactionid 或 tuple wait 就把任何一个改写成“已证实”。

## 10. 为什么 wait telemetry 仍有 sampling bias

5 Hz 意味着理论间隔 200 ms。持续时间明显短于间隔的 wait 可能完全落在两次查询之间；较长 wait 更
容易被重复采到。因此行数不是事件数，某类别占比也不是精确时间占比。

正确表述是：

> Sampling-based telemetry observes sufficiently long-lived waits visible at sample time; it is not an exhaustive event trace.

本轮记录了 sample interval、successful samples、observed wait samples、observed waiting backends、
query errors、drops 和 overflow，从而让读者能判断缺失边界。

## 11. 为什么 4+4 仍不是大样本统计实验

4 OFF + 4 ON 比旧 3+3 多两个观察，并通过两个反向 mini-block 降低简单的早晚顺序混淆。但每种模式
仍只有 4 个样本，claim-p95 的范围很大：OFF 281.941 ms，ON 372.237 ms；ON 的 range/mean 甚至为
0.731。它不能提供稳定的总体方差估计或强统计功效。

四个相邻 pair 的 claim-p95 变化为 -19.77%、-51.20%、-8.45%、-35.99%，说明高竞争环境具有明显
波动。冻结的中位数工程门槛仍然可以作 fail-closed 决策，但不能被包装成显著性或生产容量证明。

## 12. 为什么 qualification 和 formal attribution 必须拆开

若同一 workflow 在仪器刚通过时立即运行 H1/H2/H3，人们很容易看到诊断数据后顺手改 hypothesis、
阈值或 scheduler，破坏预注册。拆开后，第一阶段只回答“这把尺能否使用”，第二阶段才回答“用它
测什么以及如何判定”。

本轮 workflow 从设计上没有 formal-attribution job。即使结果为 VALID，也只能输出
`QUALIFIED_FOR_FUTURE_FORMAL_ATTRIBUTION` 并停止；实际结果 INVALID，更必须停止。

## 13. 为什么 Candidate 4 仍然不能启动

正式 targeted 4-to-8 scaling 仍是 `NEGATIVE_SCALING`，但根因未知。三种 observer 已经无法证明自己
足够低扰动：两次同步方案失败，本次被动 PostgreSQL 方案也失败。此时继续设计 Candidate 4 等于在
没有可信因果证据时猜测实现，并违反 scheduler candidate budget = 0。

stop rule 明确禁止 Observer v4、async observer、eBPF v1、继续扫频直到过门、增加 repetitions、调
阈值和直接改 scheduler。工程动作转为保存事实、文档和学习，而不是无限优化仪器。

## 14. 面试中如何解释“我们主动拒绝了自己的 instrumentation”

可以这样说：

> 我们先发现正式扩展性为负，但没有立即猜根因。前两种 transaction 内 observer 都让 claim p95 的
> 绝对变化超过 10%。随后把测量移到独立 PostgreSQL 连接和进程，限制为 5 Hz、固定只读 SQL、流式
> 有界输出，并预注册 4 OFF + 4 ON。吞吐扰动只有 0.43%，但 claim p95 仍变化 28.04%。虽然方向是
> 变快，我们仍按 absolute gate 判无效，保全 151/151 哈希一致的证据，并停止 H1/H2/H3 和 Candidate
> 4。我们优先保护结论可信度，而不是追求一张绿色报告。

这段经历体现的不是“性能问题没解决”，而是能够区分代码事实、测试事实、观察、推导、推断和假设，
并在工具不可信时主动停止因果主张。

## 实施过程中的具体问题与效果

1. 工作负载身份最初没有独立绑定 queue/distribution/workers/batch/sample_jobs。先写 RED，再让 assessor
   从 arm 派生并验证元数据，效果是 metadata spoof 现在 fail closed。
2. source lock 最初只覆盖 `app/ scripts/`。扩大到 migration、deploy、依赖与配置后，行为漂移被锁定，
   docs/results 仍可保全，避免“锁整个仓库”阻断证据提交。
3. 第一轮普通 CI 暴露 psycopg 的 `%s` 参数解析会把 ILIKE 中的字面 `%` 当占位语法。先补 RED，再把
   四个 pattern 改为 `%%`；两次普通 CI 随后完整通过。
4. 第一次 formal run `31420616109` 在任何 repetition 前失败：uv 创建的 venv 没有 `python -m pip`。
   失败环境仍由 bot 保全；随后以独立 addendum 记录，只把 preflight 改成 `uv pip check`，没有改测量
   代码或实验阈值。
5. 第二次 run `31421039618` 才执行精确 8 次并停止。assessor 非零不是 workflow 故障，而是预期的
   fail-closed verdict；preservation job 仍成功提交证据。
6. logical fixture counts 每次前后都为 0，但 database size 从 9.21 MB 增到 17.47 MB。我们记录这项物理
   漂移，不把 counterbalancing 说成能消除所有时间因素。

最后应牢记：CI green 不等于 production ready；正确性 benchmark 不等于普遍正确；wait sample 不等于
因果证明；measurement system valid 也不等于 H1/H2/H3 已证实；而本项目甚至没有达到 measurement
valid，因此最诚实、也是唯一符合预注册的结果就是停止。
