# AI EvalOps Scheduler Performance — Teaching Handoff

Updated: 2026-08-09
Audience: 下一位负责带用户学习本项目的 ChatGPT/Codex
Release context: Candidate 2 correctness-qualified, concurrent 20:1 fairness failed, v0.1.0 `NOT_READY`

## 教学使用方式

每章都从本仓库的一段真实源码、测试和 GitHub Actions 实验出发。讲解时先让学习者预测，再打开证据；
不要把结论变成背诵题。路径默认相对仓库根目录。当前证据主入口是
`docs/release/v0.1.0/final_scheduler/`，真实失败 bundle 在
`docs/results/release/v0.1.0/targeted-gh-31318923861-1/` 与
`targeted-gh-31319556885-1/`。

## 1. PostgreSQL MVCC

- **概念与项目缘由：** MVCC 让读者看到一致快照，写者通过新版本与锁协调；本项目同时提交 Job、Attempt、
  lease、Audit、Outbox，既需要可见性原子性，也需要显式处理并发写冲突。
- **源码/测试/真实实验：** 看 `app/jobs/claiming.py` 的 Phase B、`app/jobs/results.py` 和
  `tests/concurrency/test_job_claiming.py`；run `31319556885` 的 1,200 个终态 Job 验证提交后 reconciliation。
- **历史错误、失败原因与最终方法：** 旧推理把“查询能看见 eligible row”当成“必能 claim”；MVCC 快照与并发
  锁会让状态在事务间变化。最终方法是在锁后重新检查，并用一个事务写完 durable side effects。
- **Trade-off/面试角度：** 一致性更强意味着更多锁竞争；面试官可能问 MVCC 为什么没有消除 deadlock。
- **练习：** ①画出两个 Worker 的快照；②解释锁后 recheck；③找出 Phase B 原子写集合。

## 2. Row lock

- **概念与项目缘由：** 行锁保护特定记录的并发修改；调度器需要防止两个 Worker durable claim 同一 Job。
- **源码/测试/真实实验：** 看 `build_tenant_job_claim_statement()` 与 10W/100J 测试；CI
  `31318298660` 完成 2,000 unique claims/Attempts，无重复。
- **历史错误、失败原因与最终方法：** 旧设计同时锁 Job/Tenant，把 Tenant 变成热点；最终把短 Tenant turn 与
  Job durable claim 拆成两个事务，Job 继续以 `FOR UPDATE ... SKIP LOCKED` 保证唯一性。
- **Trade-off/面试角度：** 行锁粒度小但锁顺序仍可构成环；面试官会问“行锁是否天然没有死锁”。
- **练习：** ①标注 Phase A/B 锁行；②构造重复 claim 竞态；③解释 unique Attempt 的第二道保护。

## 3. `FOR UPDATE`

- **概念与项目缘由：** 最强常用行锁之一，阻止其他 writer 和 key-sharing reader；适合真正要修改/占有 Job。
- **源码/测试/真实实验：** `app/jobs/claiming.py` 的 Job selector 保留该锁；
  `test_external_tenant_for_update_exposes_fk_lock_diagnostic` 与 run `31314586983` 捕获 `55P03`。
- **历史错误、失败原因与最终方法：** 测试长期对 Tenant 使用它，导致 durable claim 的 FK `KEY SHARE` 等待，
  scope 又等待 claim，CI 卡到 6 小时。最终它只用于需要强占的 Job，外部强锁保留为 bounded negative diagnostic。
- **Trade-off/面试角度：** 保护强但兼容性差；面试官会要求解释为何“不修改主键”时可能过强。
- **练习：** ①查冲突矩阵；②预测 Tenant U + Audit insert；③解释为什么 Job 仍应 U。

## 4. `FOR NO KEY UPDATE`

- **概念与项目缘由：** 仍能串行化同一行的普通 writer，但允许 `KEY SHARE`；适合只更新
  `last_scheduler_turn_at` 或不改 Run key 的 writer guard。
- **源码/测试/真实实验：** `build_claim_candidates_statement()` 与
  `build_run_guard_for_completion_statement()`；CI `31315634340`、`31319292162` 验证 Tenant/Run 两种用途。
- **历史错误、失败原因与最终方法：** Tenant/Run 原先用 U，分别导致 FK 阻塞与 Run↔Job deadlock。compile RED
  先证明旧 SQL，再以 `key_share=True` 生成 NKU，保留 writer 互斥并兼容 FK KS。
- **Trade-off/面试角度：** 更弱不是无锁，仍可能等待另一个 NKU；面试官会问弱化是否破坏互斥。
- **练习：** ①编译 PostgreSQL SQL；②设计两个 NKU writer 实验；③说明为何不能改成纯 SELECT。

## 5. `FOR KEY SHARE`

- **概念与项目缘由：** 保护被引用 key 不被删除/改键；PostgreSQL 在外键检查中可能隐式使用它。
- **源码/测试/真实实验：** `app/jobs/results.py` 显式 Tenant KS；Outbox/Audit 外键产生隐式语义；lock artifact
  `final-scheduler-lock-diagnostics-31314586983-1` 显示 target 等 transaction id。
- **历史错误、失败原因与最终方法：** 过去只审计显式 ORM lock，漏掉 FK reader；最终把 FK KS 纳入
  `LOCK_ORDER.md`，并让 Tenant/Run guard 使用兼容的 NKU。
- **Trade-off/面试角度：** KS 读并非“无锁”；面试官可能让你解释为什么 INSERT 会等待已有行锁。
- **练习：** ①列出 Audit/Outbox FK；②画 KS 与 U/NKU；③用最小两事务复现。

## 6. 锁冲突矩阵

- **概念与项目缘由：** 冲突矩阵回答某锁能否与另一个锁共存，是判断等待边和死锁环的基础。
- **源码/测试/真实实验：** `final_scheduler/01_LOCK_DIAGNOSTIC.md`、`03_LOCK_MODE_EXPERIMENT.md`；真实对照为
  Tenant U→`55P03`，Tenant NKU→durable claim bounded success。
- **历史错误、失败原因与最终方法：** 旧分析用“锁了/没锁”二分法，无法解释同一 FK 在 U 下阻塞、NKU 下成功。
  最终逐实体写显式锁、隐式 FK 锁及兼容性。
- **Trade-off/面试角度：** 矩阵能证明一条边是否存在，不能单独证明系统永不死锁。
- **练习：** ①补全 U/NKU/KS 三格；②分析 Run deadlock；③找一个兼容但仍可能慢的路径。

## 7. Foreign Key 的隐式 lock semantics

- **概念与项目缘由：** 插入子表必须确认父 key 存在且不会被并发删改，因此简单 INSERT 也会参与父表锁图。
- **源码/测试/真实实验：** `AuditEvent.tenant_id`、Outbox 的 Tenant/Run FK；
  `tests/concurrency/test_tenant_claim_parallelism.py` 与 attempt 1 PostgreSQL deadlock log。
- **历史错误、失败原因与最终方法：** “Phase B 只显式锁 Job”被误说成“事务不碰 Tenant/Run lock”。最终文档
  使用“Job-only explicit lock，但 FK 仍有 key-preserving lock semantics”的精确表述。
- **Trade-off/面试角度：** FK 增加一致性也增加隐藏依赖；面试官会问删除 FK 是否是性能修复，答案通常不是。
- **练习：** ①从 ORM 画 FK 图；②预测父行 U 时子 INSERT；③提出不删除 FK 的修法。

## 8. Job-only explicit 不等于事务永远不涉及 Tenant

- **概念与项目缘由：** 显式锁集合只描述 SQL 中的 `FOR ...`，事务还会因 FK、UPDATE、索引和约束获得锁。
- **源码/测试/真实实验：** Phase B 在 `app/jobs/claiming.py` 只显式锁 Job，但会插 Audit/Outbox；H2 artifact
  证明 target 已持 Audit RowExclusive，同时等待 Tenant 相关 transaction lock。
- **历史错误、失败原因与最终方法：** 旧测试把完整 durable claim 当 selector 测试，导致错误合同。最终拆成
  selector-only 与 full-write diagnostic，并在设计文档保留限定词。
- **Trade-off/面试角度：** 精确术语较长但避免错误架构结论；面试官会追问“SQL 没写 Tenant lock 为何阻塞”。
- **练习：** ①列 Phase B 每次写入；②区分显式/隐式锁；③改写一句不严谨的架构描述。

## 9. `SKIP LOCKED`

- **概念与项目缘由：** 遇到已锁候选时不等待而跳过，让并发 consumer 继续取其他可用工作。
- **源码/测试/真实实验：** Tenant fast selector 与 Job selector 都使用；
  `test_fair_turn_reservation_skips_locked_tenant_for_other_tenant` 在真实 PostgreSQL CI 通过。
- **历史错误、失败原因与最终方法：** 单独使用它没错，但与 pre-lock rank pruning 组合会让某 Tenant 的 locked
  head 被跳过后没有次选 Job。最终 Phase A 选 Tenant，Phase B 再在该 Tenant 内锁 Job。
- **Trade-off/面试角度：** 高吞吐、非阻塞，但天然不保证严格队列顺序或公平。
- **练习：** ①模拟 A 锁住时 B 前进；②解释 starvation 风险；③比较无 SKIP 的等待 fallback。

## 10. 为什么适合 queue consumer

- **概念与项目缘由：** 多 Worker 不需要中央协调就能各自取不同行，事务提交就是 durable ownership 边界。
- **源码/测试/真实实验：** `SQLAlchemyJobClaimer.claim()`、EvaluationWorker；10W/100J 20 次 drain 证明并发
  consumer 无重复，targeted arms 使用真实 worker 而非纯 SQL microbenchmark。
- **历史错误、失败原因与最终方法：** 只看 FIFO 会忽略多租户公平，只看公平又可能引入热点。最终保留 PostgreSQL
  queue，把公平 reservation 与 durable Job claim 分离。
- **Trade-off/面试角度：** 少基础设施、强事务一致性；极端规模下可能遇到数据库争用与扫描成本。
- **练习：** ①定义 claim 原子边界；②比较消息队列 ack；③列出何时才考虑外部 broker。

## 11. Rank pruning：无并发时为何数学正确

- **概念与项目缘由：** 对每个 Tenant 按优先级/时间编号，只保留每租户前若干候选，可减少 WindowAgg 后续工作。
- **源码/测试/真实实验：** 历史 `scripts/fair_capacity_evidence.py` 的 rank/candidate cardinality 检查与
  1k/10k/100k EXPLAIN bundle；无锁快照中 top-ranked row 确实代表该 Tenant 最优 Job。
- **历史错误、失败原因与最终方法：** 旧方法把静态集合上的正确性外推到并发锁集合；被锁 row 会在 rank 后消失，
  但同 Tenant rank 2 已被剪掉。最终不把 pre-lock rank 当作并发 fallback 保证。
- **Trade-off/面试角度：** 减少计划成本，却可能改变并发可达集合；面试官会区分关系代数与锁时语义。
- **练习：** ①证明静态 top-1；②加入 locked head 反例；③写出需要的并发不变量。

## 12. Pre-lock pruning + `SKIP LOCKED` 为什么出问题

- **概念与项目缘由：** 先把每租户候选裁成一个，再在外层跳锁，会把“本租户下一 Job”从候选集彻底删除。
- **源码/测试/真实实验：** `docs/release/v0.1.0/perf_fix/` 的 H1/负面证据；同租户高并发曾出现 false empty 与
  retry amplification，后来 20×10W 测试再次抓到 9/10 first wave。
- **历史错误、失败原因与最终方法：** 旧 SQL 在无锁 EXPLAIN 中更快，却破坏并发 fallback。最终两阶段先安全
  reserve Tenant，再在租户内对 Job 使用 `SKIP LOCKED`，Candidate 2 仅在证明仍有 eligible work 时有界等待 turn。
- **Trade-off/面试角度：** 多一次事务/查询换取更正确的候选语义，但产生 reservation miss。
- **练习：** ①画候选集合变化；②构造 rank1 被锁；③比较扩大 rank 与两阶段方案。

## 13. Tenant hot row

- **概念与项目缘由：** 多 Worker 为同一 Tenant 同时更新一行，会把本可并行的 Job 消费串行在 Tenant row 上。
- **源码/测试/真实实验：** 历史 Job+Tenant 联合锁路径、`test_fair_turn_reservations_are_mutually_exclusive`；
  historical 100k single/w8 的 41s p95/504 retries 是负面证据，不是当前值。
- **历史错误、失败原因与最终方法：** 旧事务长时间同时持 Tenant+Job，放大热点。最终 Tenant lock 只存在于短
  Phase A，提交后 Phase B 再锁 Job。
- **Trade-off/面试角度：** 公平元数据天然是共享点；缩短临界区降低放大，但不能保证零争用。
- **练习：** ①用 Little's Law 思考等待；②标出旧/新持锁时间；③设计热点指标。

## 14. Two-phase scheduler

- **概念与项目缘由：** Phase A 决定哪个 Tenant 获得公平轮次，Phase B 决定并 durable claim 具体 Job。
- **源码/测试/真实实验：** `app/jobs/claiming.py` 的 `_reserve_tenant_turn()` 与 tenant-scoped claim；
  production overlap、reservation crash、10W drain 均在 CI 验证。
- **历史错误、失败原因与最终方法：** 单事务 Tenant→Job 扩大锁区并形成热点；最终用两个 commit boundary 切断
  Tenant→Job 同事务锁边，同时承认两阶段 race。
- **Trade-off/面试角度：** 并行性更好但 reservation 与实际 Job claim 可能脱节。
- **练习：** ①画事务时序；②列四个 crash point；③解释为何不是分布式两阶段提交。

## 15. Fair-turn reservation

- **概念与项目缘由：** 短事务更新 `Tenant.last_scheduler_turn_at`，为同优先级租户提供轮转信号。
- **源码/测试/真实实验：** Phase-A selector、reservation mutual exclusion/other-Tenant progress 测试；targeted
  20:1 的 first durable claim position 是最终公平门禁。
- **历史错误、失败原因与最终方法：** 过强 U 会阻塞 FK；完全不锁又会让两个 writer 同时获得 turn。最终 NKU+SL
  作为最小充分锁，且只更新时间戳。
- **Trade-off/面试角度：** reservation fairness 不自动等于 durable completion fairness，正是 w8 失败揭示的边界。
- **练习：** ①区分 reserved/claimed 顺序；②解释 position 4；③设计可证明的公平不变量。

## 16. Durable Job claim

- **概念与项目缘由：** Worker 只有在 Job 状态、owner、expiry、version、Attempt、Audit、Outbox 同一事务提交后
  才真正拥有任务。
- **源码/测试/真实实验：** `SQLAlchemyJobClaimer.claim()`；10W/100J 与 targeted reconciliation；事件时间在
  claim 返回后记录，因此公平位置绑定 durable completion。
- **历史错误、失败原因与最终方法：** 把 selector success 当 claim success 会高估公平/吞吐。最终所有证据按
  commit 后 receipt 计数，并以数据库终态与 Attempt 对账。
- **Trade-off/面试角度：** durable transaction 较重，却提供恢复和审计基础。
- **练习：** ①列原子字段；②解释 commit 前 crash；③设计重复 receipt 检测。

## 17. Short reservation 与 long external `FOR UPDATE` 不是同一场景

- **概念与项目缘由：** 生产 reservation 快速更新并 commit；诊断外部事务故意长期持强锁，两者持锁时间和兼容性
  完全不同。
- **源码/测试/真实实验：** production overlap test 与 external U negative diagnostic 并列；前者成功，后者
  bounded `55P03`，由 `pg_blocking_pids` 证明。
- **历史错误、失败原因与最终方法：** 旧测试让外部 lock scope 等待 full claim，制造自身 wait cycle并错误要求
  production 无视任意强锁。最终拆约并为每个测试写明语义。
- **Trade-off/面试角度：** 负面诊断仍有价值，但不能冒充生产合同。
- **练习：** ①比较两条 timeline；②指出循环等待；③给测试重新命名。

## 18. Test harness deadlock / wait cycle

- **概念与项目缘由：** 测试控制流本身可以让一个事务持锁并等待被该锁阻塞的 task，从而制造无限等待。
- **源码/测试/真实实验：** `test_tenant_claim_parallelism.py` 的重构前后合同；旧 push/PR runs
  `31297535370`/`31297538171` 均约 6 小时后取消。
- **历史错误、失败原因与最终方法：** 没有 DB/Python/step timeout，failure 无法转成信息。最终数据库 timeout、
  `asyncio.wait_for` 和 10 分钟 CI step 三层保护，并保存锁快照。
- **Trade-off/面试角度：** timeout 能止血但不能解释根因；必须与数据库证据一起使用。
- **练习：** ①画 harness wait-for graph；②区分测试 bug/生产 bug；③选择三层 timeout 值。

## 19. `lock_timeout`

- **概念与项目缘由：** 只限制等待锁的时间；本项目用 `SET LOCAL` 将锁语义错误转成可断言的 SQLSTATE `55P03`。
- **源码/测试/真实实验：** `tests/postgres_test_support.py` 默认约 1.5s；H2 external U 实验按预期 fail-fast。
- **历史错误、失败原因与最终方法：** 过去无限等待到 CI 上限；最终 test-only transaction local 设置，不修改
  production PostgreSQL 配置或 lease。
- **Trade-off/面试角度：** 太短会引入 CI 抖动，太长降低诊断速度；它不限制 CPU 慢查询。
- **练习：** ①区分 lock/statement timeout；②验证 SQLSTATE；③说明为何不用 production 全局值。

## 20. `statement_timeout`

- **概念与项目缘由：** 限制一条 SQL 的总执行时间，覆盖非锁等待或计划执行异常，是 lock timeout 之外的兜底。
- **源码/测试/真实实验：** `tests/postgres_test_support.py` 约 8s local 设置，外加 Python 约 15s 和 CI 10min；
  后续 CI 从 6h hang 变成约 4min 可诊断失败。
- **历史错误、失败原因与最终方法：** 只有 workflow 总上限时定位粒度太粗。最终按 DB operation、coroutine、step
  分层，并在错误中带 operation name。
- **Trade-off/面试角度：** 会取消合法慢 SQL，测试值必须留合理余量；不能拿它掩盖真实性能问题。
- **练习：** ①设计 timeout 层级；②模拟非锁慢查询；③解释为什么 step timeout 最长。

## 21. 为什么 lock-sensitive test 必须 fail fast

- **概念与项目缘由：** 并发测试失败应在秒级转为明确证据，否则 CI 时间只说明“没结束”，不能区分慢、阻塞或死锁。
- **源码/测试/真实实验：** `postgres_test_support.py`、并发测试的 `wait_for`、CI same-tenant step timeout；
  `1b6a2f8` 后 run `31314066767` 约 4 分钟给出 FK lock failure，替代 6 小时取消。
- **历史错误、失败原因与最终方法：** 旧测试只靠 GitHub 6h 上限，artifact/堆栈不足。最终先让数据库报具体锁错误，
  Python 报 operation，workflow 只作最后兜底。
- **Trade-off/面试角度：** fail-fast 让反馈可靠，但 timeout 本身不是修复；面试官会问如何避免 flaky threshold。
- **练习：** ①为新锁测写三层保护；②区分预期 timeout/意外 timeout；③规定 artifact always-upload。

## 22. `pg_stat_activity`

- **概念与项目缘由：** 展示会话 PID、状态、wait event 与当前/最近 query，用于定位谁在等什么。
- **源码/测试/真实实验：** `wait_for_postgres_lock_snapshot()` 查询它；run `31314586983` 记录 blocker PID 397、
  target PID 399 与 target 的 transactionid 等待。
- **历史错误、失败原因与最终方法：** 过去仅凭 Python task stack 猜 FK。最终为被测/observer connection 设置
  `application_name`，按 PID 精确抓快照并写 JSONL。
- **Trade-off/面试角度：** query 字段可能只显示最近 SET LOCAL，需结合 locks/blocking_pids，不可单表定罪。
- **练习：** ①解释 state/wait_event；②过滤 observer；③关联一条锁记录。

## 23. `pg_locks`

- **概念与项目缘由：** 给出 relation/tuple/transactionid 等锁、mode 和 granted 状态，补足 activity 的等待描述。
- **源码/测试/真实实验：** `tests/postgres_test_support.py` 采集 target/blocker 相关行；artifact 显示 target 对
  transaction 1191 的未授予 ShareLock，blocker 持 ExclusiveLock。
- **历史错误、失败原因与最终方法：** 只看 relation lock 容易误判，因为阻塞常呈现为 transactionid lock。
  最终把 PID、activity、blocking list、全部相关 locks 一起保存。
- **Trade-off/面试角度：** 锁表瞬时且解释复杂；面试官会让你说明 tuple 等待为何显示 transactionid。
- **练习：** ①找 granted=false；②配对同一 transactionid；③识别 relation OID。

## 24. `pg_blocking_pids`

- **概念与项目缘由：** PostgreSQL 直接返回阻塞某 backend 的 PID，快速构造 wait-for edge。
- **源码/测试/真实实验：** helper 查询 `pg_blocking_pids(pid)`；H2 证据 `pg_blocking_pids(399)=[397]`。
- **历史错误、失败原因与最终方法：** 过去通过时间接近推测 blocker，可能把观察者或无关连接算入。最终以固定
  application name 找 target，再让数据库报告 blocker。
- **Trade-off/面试角度：** 它给出边但不解释业务语义，必须回连 query、FK 和 lock mode。
- **练习：** ①画 397→399；②解释多 blocker；③设计循环检测。

## 25. `WindowAgg`

- **概念与项目缘由：** 公平 SQL 用窗口函数为每 Tenant 的 Job 排 rank；候选大时排序/窗口成本显著。
- **源码/测试/真实实验：** `scripts/fair_capacity_evidence.py` 解析 plan 中 `WindowAgg`；历史 100k EXPLAIN
  bundle 发现完整候选处理和重复窗口执行。
- **历史错误、失败原因与最终方法：** 最初仅观察总 latency，没有核对 candidate cardinality。后来 assessment
  曾因误读 Run Condition fail-closed；最终 verifier 明确校验节点和基数，并保留 raw JSON。
- **Trade-off/面试角度：** SQL 表达公平清晰，但大集合代价高；优化计划不能越过并发语义。
- **练习：** ①读一份 EXPLAIN；②区分 input/output rows；③解释 rank predicate 的位置。

## 26. `MATERIALIZED` CTE

- **概念与项目缘由：** 强制 PostgreSQL 先计算 CTE，避免 planner 内联后在外层 join 中重复执行窗口子查询。
- **源码/测试/真实实验：** 历史 fair selector 与 `perf_fix/`；materialization 后容量 plan/throughput 改善，
  但正式 broken-fair 4/8 scaling 仍失败。
- **历史错误、失败原因与最终方法：** 未物化版本单次逻辑正确却被 planner 重复执行。最终将它作为计划形状修正，
  不宣称解决了多 Worker contention。
- **Trade-off/面试角度：** 避免重复执行但失去某些 predicate pushdown，也需要内存/临时存储。
- **练习：** ①比较两份 plan；②找重复 loops；③说明何时不应强制 materialize。

## 27. EXPLAIN 变快不代表 multi-worker scaling 变好

- **概念与项目缘由：** EXPLAIN 衡量一条查询的计划/执行；多 Worker 吞吐还受锁、连接、事务、重试和结果写入影响。
- **源码/测试/真实实验：** historical fair/legacy plan 对照与 formal worker runs；plan ratio 可改善，而旧 formal
  source 仍在 4→8 负扩展。Candidate 2 partial ratio 也只能标 `LIMITED`。
- **历史错误、失败原因与最终方法：** 曾把 plan A/B 当端到端 worker A/B。最终文档明确同 snapshot SQL 对照与
  real EvaluationWorker throughput 是两种证据。
- **Trade-off/面试角度：** microbenchmark 定位局部原因快，但外部有效性低。
- **练习：** ①列出 EXPLAIN 未覆盖因素；②设计 worker benchmark；③识别错误简历 claim。

## 28. Retry amplification

- **概念与项目缘由：** 多 Worker 争同一短资源时，一次逻辑 claim 可触发多次 reservation probe/retry，负载反过来
  延长临界区，形成放大。
- **源码/测试/真实实验：** claimer contention counters、8W artifacts；早期样本 17 attempts/9 retries，
  corrected Candidate-2 diagnostic 11 attempts/3 fallbacks、ratio 0.375。
- **历史错误、失败原因与最终方法：** 试图仅提高 retry 上限会制造更多数据库压力且仍可能 false empty。Candidate 2
  保留非阻塞快路，只在 positive eligibility probe 后进行一次等待 fallback。
- **Trade-off/面试角度：** fallback 提高成功概率但可能等待；面试官会问为何不是 20→100 参数调整。
- **练习：** ①计算 retry/success；②画正反馈环；③设计 fallback 指标。

## 29. Reservation miss

- **概念与项目缘由：** Worker 已提交 Tenant turn，但进入 Phase B 时该 Tenant 的最后一条 Job 被别人取走。
- **源码/测试/真实实验：** metrics `tenant_turn_reserved_total`、`tenant_turn_without_job_total`、
  `reservation_miss_rate`；targeted/capacity runner 记录 reservation 与 Job-claim latency。
- **历史错误、失败原因与最终方法：** 两阶段最初缺少观测，empty 容易被误认作无工作。最终分别记录 reservation miss、
  empty-while-eligible、waiting fallback，且不以 Tenant ID 作高基数标签。
- **Trade-off/面试角度：** miss 不破坏 correctness，却浪费公平轮次和查询；面试官会问阈值如何定。
- **练习：** ①构造 last-job race；②区分三种 empty；③计算进程合并 miss rate。

## 30. Lease

- **概念与项目缘由：** durable 时间窗内由某 Worker 拥有 Job；Worker 崩溃后过期可回收，避免永久 running。
- **源码/测试/真实实验：** `app/jobs/lease.py`、claimer Phase B、`scripts/fault_matrix_driver.py` 场景；historical
  A–I fault run 验证过 reclaim，但当前候选未重跑 fault，必须标历史。
- **历史错误、失败原因与最终方法：** 曾从 claim transaction 开始过早计算 execution lease，100k 慢 claim 会吃掉
  执行时间。最终从成功 claim 后界定执行租约，不增加 lease duration 掩盖 scheduler delay。
- **Trade-off/面试角度：** 太短误回收，太长恢复慢；lease 不是 exactly-once。
- **练习：** ①画 lease 生命周期；②解释过期 reclaim；③反驳“加长 lease 修调度”。

## 31. Heartbeat

- **概念与项目缘由：** 活跃 Worker 周期性延长 lease，并携带 owner/version 证明仍是当前持有者。
- **源码/测试/真实实验：** `app/jobs/heartbeat.py` 与 `tests/unit/workers/test_lease_runner.py`、并发 stale heartbeat
  测试；历史 fault 证据验证过期/恢复路径。
- **历史错误、失败原因与最终方法：** 若只按 job_id 更新，旧 Worker 可复活旧 lease。最终单条 conditional
  UPDATE/RETURNING 同时检查 owner、version、live expiry 和状态。
- **Trade-off/面试角度：** 心跳增加写流量；间隔必须小于 lease 但留抖动余量。
- **练习：** ①写条件谓词；②模拟 stale heartbeat；③讨论 DB outage 时行为。

## 32. Version fencing

- **概念与项目缘由：** 每次 claim/reclaim 增加 version；结果、失败和 heartbeat 必须提供精确版本，隔离旧执行者。
- **源码/测试/真实实验：** Job version 在 claiming/result/failure paths；`test_job_claiming.py` 与 historical fault
  scenarios C/D。targeted 完成 arms 的 attempt/version reconciliation 为 0 mismatch。
- **历史错误、失败原因与最终方法：** 仅凭 worker_id 或状态不够，重启/重取后旧请求仍可能迟到。最终 owner+version+
  expiry 联合 fence。
- **Trade-off/面试角度：** 需要客户端传播 receipt；换来清晰的代际所有权。
- **练习：** ①模拟 v1/v2；②找出所有 fence check；③解释版本为何单调。

## 33. Stale completion

- **概念与项目缘由：** lease 过期且 Job 被新 Worker 领取后，旧 Worker 的 success/failure 晚到。
- **源码/测试/真实实验：** `app/jobs/results.py`、`failures.py`、fault driver；historical A–I ×3 中 stale
  success/failure 各尝试 3 次、accepted 0；当前代码合同未削弱，但 current fault 是 `NOT_RUN`。
- **历史错误、失败原因与最终方法：** 若按 job_id 直接写结果会产生重复/覆盖。最终在锁定行后检查 owner、version、
  live expiry，并以 unique CaseResult/Attempt 约束兜底。
- **Trade-off/面试角度：** 拒绝旧结果可能浪费昂贵计算，但保护状态真实性。
- **练习：** ①画 late success race；②区分 attempted/accepted；③设计客户端错误响应。

## 34. 为什么不能为了性能削弱 fencing

- **概念与项目缘由：** 性能门与 correctness 门独立；降低 owner/version/expiry 校验可能让吞吐变好，却允许错误结果提交。
- **源码/测试/真实实验：** final sprint 明令不改 fencing；Candidate 2 只改 Tenant selection fallback，Run fix 只改
  兼容 lock mode。targeted correctness 仍 1,200/1,200。
- **历史错误、失败原因与最终方法：** 把长 lease/弱 fence 当调度优化会隐藏等待并扩大 stale window。最终 release
  fail-closed：公平失败就 `NOT_READY`，不交换正确性。
- **Trade-off/面试角度：** 正确性约束可能限制峰值吞吐，但属于不可谈判边界。
- **练习：** ①列不可变 invariants；②评审一个去 version 的“优化”；③设计性能与正确性双门。

## 35. 4→8 self scaling

- **概念与项目缘由：** 在同一 source、runner、workload/repetition 内比较 4 与 8 Worker，减少跨环境混杂。
- **源码/测试/真实实验：** `scripts/targeted_scheduler_evidence.py` 冻结规则：四重复中位数，若
  `throughput_8 < throughput_4*0.95` 则 `NEGATIVE_SCALING`。attempt 2 只有 rep1 三组 ratio。
- **历史错误、失败原因与最终方法：** 旧文档曾误把绝对 Jobs/s 差写成百分比，也曾用不同 CPU run 做强因果判断。
  最终优先 self-scaling，并因重复不全标 `LIMITED`。
- **Trade-off/面试角度：** 控制环境更好，但仍受共享 runner 噪声，需要重复和 counterbalance。
- **练习：** ①计算三个 ratio；②解释为何不是正式 verdict；③选择 median 而非单样本。

## 36. Same-runner paired benchmark

- **概念与项目缘由：** 在同一 runner 上成对执行 baseline/candidate，交替顺序，减少硬件、邻居和时间漂移。
- **源码/测试/真实实验：** final protocol 设计了 A/B/C same-runner，但因 targeted fairness failure 标
  `NOT_RUN`；historical pre-fair vs fair 来自不同 EPYC CPU，不能替代。
- **历史错误、失败原因与最终方法：** 过去跨 runner 百分比被写得过强。最终必须固定 fixture/seed、配对 arm、
  counterbalance 顺序并报告 pair distribution。
- **Trade-off/面试角度：** 成本高且仍非生产环境，但因果可信度强于独立 run。
- **练习：** ①设计 ABBA 顺序；②定义 pair key；③解释未运行为何不能填历史值。

## 37. Cross-runner comparison

- **概念与项目缘由：** 不同 Actions runner/CPU/时间的结果可作趋势或历史上下文，但混入硬件和平台噪声。
- **源码/测试/真实实验：** historical pre-fair runner AMD EPYC 7763、broken-fair runner EPYC 9V74；曾观察最差
  -63.44%，保留为历史 gate 证据而非纯 scheduler 因果量。
- **历史错误、失败原因与最终方法：** 直接把两次 run 相除并称“优化回退”过度归因。最终同时报告 source、runner、
  protocol，优先 current-run self scaling 与 same-runner paired。
- **Trade-off/面试角度：** 便宜且利用已有数据，但置信度低。
- **练习：** ①列混杂变量；②改写一条过强 claim；③提出 paired replacement。

## 38. Fairness vs throughput

- **概念与项目缘由：** throughput 是单位时间完成量；fairness 是不同 Tenant 被服务的相对时序/机会，两者可冲突。
- **源码/测试/真实实验：** targeted 同时记录 Jobs/s 与 20:1 secondary first durable position。attempt 2 所有 Job
  correctness clean，但 w8 position 4 使 release 失败，不能用较高 throughput 抵消。
- **历史错误、失败原因与最终方法：** 旧优化只看 EXPLAIN/吞吐，公平语义可能退化；最终设置独立 fail-closed gate。
- **Trade-off/面试角度：** 更严格公平可能增加协调成本；面试官会让你定义可测的 fairness。
- **练习：** ①给两个反例；②解释为何 position 用 commit order；③设计双目标报告。

## 39. Fairness vs quota

- **概念与项目缘由：** fairness 决定有竞争时谁先得到服务；quota 限制某 Tenant 可消费多少资源/速率。当前系统只有
  priority+turn fairness，不是资源配额系统。
- **源码/测试/真实实验：** `last_scheduler_turn_at` 排序与 20:1 first-position test；没有 token bucket、并发上限或
  计费额度源码。position `<=2` 也不是长期带宽保证。
- **历史错误、失败原因与最终方法：** 把 20:1 早期服务结果宣传成强公平/配额 SLO 会越界。最终文档只称 controlled
  concurrent fairness contract，当前还失败。
- **Trade-off/面试角度：** 公平轻量，quota 需要持久计数和策略；两者可叠加但不等价。
- **练习：** ①写两个定义；②设计 quota 数据模型；③说明本 release 为什么不加。

## 40. 为什么当前仍不需要 Kafka/Celery/Temporal

- **概念与项目缘由：** 这些系统分别提供日志/消息、任务队列、工作流编排能力，但会引入新的 durable truth、运维和
  一致性边界。当前问题是 PostgreSQL scheduler 的并发公平不变量，不是消息传输能力缺失。
- **源码/测试/真实实验：** PostgreSQL 已承担 Job/lease/Attempt/Outbox，10W correctness 和故障历史证据存在；
  targeted `31319556885` 精确暴露 w8 fairness failure，换框架不会自动证明它。
- **历史错误、失败原因与最终方法：** 架构升级容易绕开根因并扩大 sprint。最终按停止规则不做 Candidate 3，也不
  引入 broker；下一阶段只写 concurrent-fairness-invariant-driven redesign proposal。
- **Trade-off/面试角度：** 当前方案基础设施少、事务边界清晰；若未来吞吐、跨区、长工作流或团队边界有证据再评估。
- **练习：** ①为三种工具分别列触发条件；②说明 Outbox 的角色；③写一份“何时迁移”的证据门。

## 教学结束时应让学习者能回答

学习者应能从 raw lock graph 推导 U/NKU/KS 的选择，从两阶段事务画出 crash/recovery，从 manifest 区分
current/historical/limited/not-run，并能解释为什么四次 CI 绿色仍不能覆盖一次冻结公平门禁失败。最终答案
必须是：当前项目有很强的 correctness 与证据工程基础，但 v0.1.0 仍是 `NOT_READY`；下一步先定义可证明的
并发公平不变量，而不是继续调参或换消息队列。
