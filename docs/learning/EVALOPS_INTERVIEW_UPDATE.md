# AI EvalOps Platform — Interview Update

Updated: 2026-08-09
Rule: 每题必须回答“源码在哪里、测试怎么证、真实实验是什么、证据边界是什么”，不能只讲通用定义。

## 1. 为什么 PostgreSQL 可以做 Job Queue？

回答线索：`app/jobs/claiming.py` 用事务、行锁和 `SKIP LOCKED` 原子 claim；Job/Attempt/lease/Audit/Outbox
共享同一 durable transaction。`31318298660` 的 20×10W/100J 证明 2,000 unique claims/Attempts。限制是这
不是无限规模 SLO，当前并发公平仍失败。

## 2. 为什么用 `SKIP LOCKED`？

回答线索：多 Worker 遇到已锁 Job/Tenant 时能继续处理其他行；跨 Tenant nonblocking 测试在
`test_tenant_claim_parallelism.py`。同时说明它不保证公平，且与 pre-lock rank pruning 组合曾丢失租户内 fallback。

## 3. `FOR UPDATE` 与 `FOR NO KEY UPDATE` 有什么区别？

回答线索：U 与 FK 所需 KS 冲突，NKU 与 KS 兼容，但两个 NKU writer 仍互斥。引用 Tenant U→`55P03`、Tenant
NKU→full claim success 的 H2/H3 对照，以及 `app/jobs/results.py` 的 Run NKU fix。

## 4. FK 为什么会影响锁？

回答线索：子表 INSERT 要保护父 key，产生 key-preserving lock semantics。Phase B 虽只显式锁 Job，Audit/Outbox
的 Tenant/Run FK 仍进入锁图。用 artifact `71dd44d0…` 的 PID 397/399、transaction 1191 说明。

## 5. 为什么 CI 曾卡 6 小时？

回答线索：测试事务 A 长期持 Tenant U，又在 scope 内等待事务 B；B 完整 durable claim 插 Audit 时请求 FK KS，
被 A 阻塞，形成 test-harness wait cycle。旧 runs `31297535370`/`31297538171` 直到平台上限才取消。

## 6. 怎样证明是测试 hang 还是生产 bug？

回答线索：拆 selector-only、external U negative、external NKU control、production-shaped short-overlap 四个合同；
用 `pg_stat_activity`、`pg_locks`、`pg_blocking_pids` 取证。前者定位错误测试语义；后来的 targeted attempt 1 则
真实复现 Run/Job production deadlock，说明不能一律归咎测试。

## 7. 为什么所有锁测试都要 fail fast？

回答线索：`tests/postgres_test_support.py` 的 `SET LOCAL lock_timeout/statement_timeout`、`asyncio.wait_for` 与
CI 10min step 三层保护。`31314066767` 把 6h hang 变成约 4min、带 SQLSTATE `55P03` 的诊断失败。

## 8. 为什么 EXPLAIN 无法证明 concurrency scaling？

回答线索：EXPLAIN 只覆盖 SQL plan；Worker throughput 还含锁等待、事务、retry、result commit、CPU/connection。
历史 MATERIALIZED CTE 改善 plan，但 broken-fair formal 仍 4→8 负扩展。引用 `fair_capacity_evidence.py`。

## 9. 为什么不用 Kafka？

回答线索：当前 durable truth、lease、Attempt、Outbox 已在 PostgreSQL；唯一 blocker 是 committed claim ordering 下
的并发公平，不是日志传输。引入 Kafka 会增加双写/消费语义而没有自动解决该不变量。说明未来跨区/超高吞吐有证据
时可重新评估。

## 10. 为什么不用 Celery？

回答线索：Celery 能提供任务分发，但本项目需要数据库内 Run/Job/Attempt/Result 与多租户公平、version fencing 的
原子关系。当前问题可在现有模型内精确测量；迁移会扩大 scope，且违反 final sprint 禁止项。

## 11. 为什么不用 Temporal？

回答线索：Temporal 擅长长工作流状态机，但本 RC 的核心是短 claim transaction、lease/reaper/fencing 和结果提交。
当前没有证据表明工作流编排缺失是瓶颈；先解决明确的 w8 fairness invariant。

## 12. 为什么 two-phase scheduler 会有 reservation race？

回答线索：Phase A commit 后到 Phase B 锁 Job 前，另一个 Worker 可能取走该 Tenant 最后一条 eligible Job；于是 turn
成功但无 Job。源码 metrics `tenant_turn_without_job_total`，并说明这是效率问题，不必然是 correctness error。

## 13. Reservation 成功后 Worker crash 怎么办？

回答线索：Phase A 只更新时间戳，不创建 Attempt/lease，不改变 Job 状态；crash 后 Job 仍 queued/retry-wait，可由
其他 Worker 领取。引用 `test_phase_a_reservation_crash_leaves_job_claimable_without_a_lease` 的真实 CI GREEN。

## 14. 为什么 stale result 仍然安全？

回答线索：Result/failure 要求 owner、live expiry、精确 version，且锁 Job/Attempt 后提交；旧 Worker 的 v1 在 v2 reclaim
后被拒绝。历史 fault `31275450353` 中 stale success/failure 各尝试 3 次、accepted 0；明确它是 historical。

## 15. Fairness 为什么不等于 quota？

回答线索：当前 `last_scheduler_turn_at` 影响同优先级服务次序；quota 则限制长期资源份额/速率。20:1 first position
`<=2` 只是受控早期公平合同，不是带宽配额或强公平 SLO，而且当前 w8 已失败。

## 16. Runner CPU 不同为什么削弱 historical A/B？

回答线索：pre-fair run 使用 EPYC 7763，broken-fair current-at-the-time run 使用 EPYC 9V74；CPU、邻居、时间漂移都是
混杂。-63.44% 可作为历史 gate/风险证据，不能说是纯 scheduler 因果量。

## 17. 怎么设计 same-runner benchmark？

回答线索：同一 runner、fixture、seed、数据库镜像；A/B/C counterbalanced（如 ABC/CBA 或 Latin square）；按相同
workload/worker/repetition 配对；先验证 correctness，再报告 pair median/distribution。当前协议因 targeted failure
没有运行，状态必须 `NOT_RUN`。

## 18. 为什么不删除失败实验？

回答线索：失败 bundle 证明边界和决策路径：6h hang、false-empty、targeted deadlock、targeted fairness failure。两次
targeted artifact 均 digest/source-bound 并追加保存；删除会造成 survivorship bias，也让修复失去可复核 RED。

## 19. 为什么 CI success 不等于 Release READY？

回答线索：六态独立：WORKFLOW_EXECUTED、TESTS_PASS、CORRECTNESS_PASS、EVIDENCE_COMPLETE、PERFORMANCE_PASS、
RELEASE_READY。Candidate 2/Run guard 四个 CI 绿色只覆盖测试与 correctness；targeted fairness failure 让证据链中止。

## 20. 为什么不能用更长 lease 解决 scheduler delay？

回答线索：lease 控制执行所有权恢复，不是 claim contention。加长只延迟 crash recovery、扩大 stale window，并掩盖
queue delay；final sprint 禁止用 lease 参数赌博，Candidate 2 改的是 proven false-empty reservation path。

## 21. 如果 100k 仍慢，下一步看什么？

回答线索：先分解 reservation/job-claim latency、DB waiting sessions、retry/fallback/miss、WindowAgg cardinality、buffers、
CPU/RSS 与连接等待；再设计同 runner 实验。historical 41s p95/504 retries 是定位线索，不是 current 数字。当前更早的
公平门已失败，所以本 sprint 不应直接跑 100k。

## 22. Targeted attempt 1 为什么不是 `NEGATIVE_SCALING`？

回答线索：只完成 single/w1 一个 arm，随后正确性 deadlock；assessment repetition_count=0。没有四重复 4/8 median，
所以只能记 correctness RED，不能作性能裁决。

## 23. Targeted attempt 2 的 partial 4→8 ratio 能否写简历？

回答线索：不能作为正式 scaling claim。single/balanced/skew ratio 0.8952/0.9083/0.8907 只有 repetition 1，many-small 和
后续重复未跑；只能在工程复盘里标 `LIMITED`，简历中应写证据方法和发现 fairness blocker。

## 24. Run-first 为什么不能简单删除？

回答线索：历史 commit `7d54f97` 用 Run-first 消除多个 result transaction 的 FK lock-upgrade deadlock；改回 Job-first
可能复活旧环。最终保留 Run-first，只把 U 降为 NKU，使 result writers 互斥且允许 claim Outbox FK KS。

## 25. 最终为什么停止 scheduler 开发？

回答线索：Candidate 2 是明确允许的第二次也是最后一次生产 iteration；冻结公平门失败。继续改参数/做 Candidate 3
会违反预注册停止规则并增加 p-hacking 风险。下一阶段唯一合理动作是先写“并发公平不变量驱动的 scheduler redesign
proposal”，经 RED 与同 runner 证据计划审阅后再决定是否开启实现。

## 面试表达红线

- 可以说“在真实 PostgreSQL CI 中证明并修复两类锁问题，并让失败在秒级可诊断”。
- 可以说“20×10W/100J 取得 2,000 unique claims/Attempts，随后 targeted 公平门 fail-closed”。
- 不可以说“v0.1.0 已发布/production-ready”“current 32-arm 已通过”“线性扩展”“强公平 SLO”。
- 必须主动说清 historical、current、limited 与 not-run；这是本项目最有价值的证据工程能力之一。
