# AI EvalOps Platform — Interview Update

Updated: 2026-08-10
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

回答线索：用户后来只授权一个 invariant-driven Candidate 3。它通过 ordinary correctness，但 targeted run
`31327388006` 的 source-bound release bundle 失败；规则明确 `targeted fail -> STOP`。继续修 assessor 后重跑、
改参数或做 Candidate 4 都会违反本阶段预注册停止条件。

## 26. 为什么公平 reservation 不等于公平 Job claim？

回答线索：reservation 和 Phase-B Job/Attempt/Audit/Outbox 提交是两个事务；B reservation 可先提交，但 B
Phase-B 等待时 A2/A3 仍可提交。确定性 RED 让 B 的 application receipt 到位置 8。

## 27. Candidate 3 的 linearization point 在哪里？

回答线索：Job/lease/version/Attempt/Audit/Outbox 与 per-Tenant permit `PENDING→CONSUMED` 在一个短事务提交；
application receipt 仍是冻结 gate，`scheduler_claim_sequence` 是额外 DB-linearized diagnostic。

## 28. 为什么 current position 4 不是单纯吞吐问题？

回答线索：position 4 违反 equal-priority secondary receipt `<=2` 的顺序性质；即使 Jobs/s 很高，也不能用总量
抵消被越过的可观察顺序。

## 29. 为什么不能把门禁从 <=2 改成 <=4？

回答线索：阈值在 Candidate 2 结果前已冻结。看到失败后放宽会改变被验证的假设，属于事后适配，失去独立证据价值。

## 30. deterministic concurrency RED 为什么使用 Barrier/Event 而不是 sleep？

回答线索：Barrier 定义 first wave，Event 精确暂停 B Phase-B 并释放 A；sleep 依赖 runner 调度，可能偶发绿/红且不能
说明哪个事务先发生。

## 31. reusable permit row 在 Worker crash 后如何恢复？

回答线索：permit consumption 与 Job claim 同事务；commit 前 crash 自动 rollback，state 仍 pending，其他 Worker 可再次
锁定；没有独立 permit lease 或无限增长 ticket 需要 GC。

## 32. 为什么不能让 permit 永久占用？

回答线索：current round 有 pending member 时禁止下一 round；永久 pending 会阻塞同 priority 所有 Tenant，直接违反
liveness/no-starvation。rollback、EMPTY transition 和 retry path 必须完整。

## 33. global scheduler lock 什么时候合理？

回答线索：只在 refill generation 或 tail sequence assignment 的极短数据库窗口合理；不能穿过完整 durable writes，更
不能穿过 Target/Evaluator/Worker 外部执行，否则 convoy 和吞吐上限会被放大。

## 34. 怎样证明 priority 没有被 Tenant fairness 破坏？

回答线索：round membership 只从最高 eligible priority 聚合，Job selector 再使用 exact round priority；真实 PostgreSQL
priority regression 在 Candidate 3 ordinary CI 中通过。

## 35. no starvation 怎么测试？

回答线索：不能只看一次 20:1 position。要让多个 Tenant 持续 eligible，控制 crash/empty/lock contention，断言 generation
持续推进且每个持续 eligible Tenant 在有限 rounds 内被消费；本轮只完成了 preregistered liveness regressions，未建立长期 SLO。

## 36. 为什么 application return order 和 DB commit order 可能不同？

回答线索：事务 commit 后 coroutine 仍需恢复并返回，event loop 可让后提交的调用先记录 receipt；所以保留 DB sequence
诊断差异，但不能事后换掉 application gate。

## 37. 为什么仍要保留旧 harness？

回答线索：旧 harness 是预先冻结的用户可见 committed receipt oracle。删除它只保留新 DB sequence 会让 Candidate 3
针对新指标自证，无法证明 Candidate 2 的原始失败被修复。

## 38. 为什么 correctness/fairness PASS 仍不能 release？

回答线索：新 targeted 已有 64/64 arms、6,400/6,400 terminal 和四次 `2/2/2/2`，但 performance 是正交 gate。
single/balanced/20:1 的 w8/w4 ratio 只有 0.782511/0.772797/0.796214，低于每类都必须达到的 0.95。

## 39. 旧 Candidate 3 targeted 到底失败了什么？

回答线索：历史 run `31327388006` 不是 Job correctness 失败，而是 schema-v1
`postgres_explain_candidate_cardinality_mismatch`：fair 输出 Tenant members 1/4/2/100，assessor 错按 Jobs 1000。
该 bundle 保持 immutable FAILED。

## 40. 为什么 schema v2 不是“看到 RED 后改 oracle 作弊”？

回答线索：它在单独授权阶段先预注册单位、compatibility 与 fail-closed 条件，再写 RED；旧 bundle 不重算；新 source 先过
普通双 CI；新增 wrong-unit、wrong-cardinality、invalid Tenant count、boolean schema 与 arm spoof negatives。

## 41. 新 targeted 到底证明了什么？

回答线索：run `31352270523` 四个 rep bundle 都是 schema 2 VERIFIED；64 arms、6,400 terminal、protected counters
全 0；每次 20:1 w1/w2/w4/w8 都是 2。它证明冻结 workload，不证明 universal/production fairness。

## 42. 为什么 workflow 是 failure，但四次 repetition 又是 success？

回答线索：workflow 的执行四次、上传 artifact、提交证据、cleanup 都 success；assessment 对正式
`NEGATIVE_SCALING` 返回非 0，所以 job 最终 failure。这是 gate 正常工作，不是 infra crash。

## 43. 为什么 current performance verdict 不是 median 偶然？

回答线索：single/balanced/20:1 中每个 w8 observation 都低于每个 w4 observation；三类 median ratio 都远低于
0.95，且 w8 retries/retry-per-success/claim p95 同时上升。

## 44. 为什么 historical capacity 不能代表 Candidate 3？

回答线索：Candidate 3 增加 round refill、permit state 和 sequence lock，SQL round trips/锁热点改变。
`9987a28` 的 1k/10k/100k bundle 只能标 VERIFIED_HISTORICAL；current capacity 仍 NOT_RUN_STOPPED。

## 45. 为什么当前仍不需要 Kafka/Celery/Temporal？

回答线索：当前失败是 PostgreSQL scheduler 在 concentrated-Tenant workload 下的 scaling，不是消息传输或长工作流功能缺失；
换基础设施会扩大 durable truth/运维边界，也不会自动消除数据库协调热点。

## 面试表达红线

- 可以说“在真实 PostgreSQL CI 中证明并修复两类锁问题，并让失败在秒级可诊断”。
- 可以说“Candidate 3 在四次 source-bound targeted 中完成 64 arms/6,400 Jobs，冻结 20:1 position 全为 2”。
- 必须同句说明“三类 4→8 scaling 正式低于 0.95，因此 release NOT_READY”。
- 不可以说“v0.1.0 已发布/production-ready”“current 32-arm 已通过”“线性扩展”“强公平 SLO”。
- 不可以把 frozen workload fairness PASS 外推成 universal/production fairness。
- 必须主动说清 verified-current、failed-current、historical 与 not-run；这是本项目最有价值的证据工程能力之一。
