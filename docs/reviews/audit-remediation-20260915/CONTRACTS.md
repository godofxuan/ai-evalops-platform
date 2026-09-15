# 锁、时间与评分版本合同

本轮从 903ed7ca44e452faa93a62a9515f7fba733a8d1d 独立修复，不更改 main、RAG、旧报告、gold 或正式质量门槛。最新执行结论以 CLOSEOUT_RESULTS.md 与交付回执为准。

## 1. 时间不是请求开始时间

租约在线性化授权检查点必须有效：获得本次决策需要的全部行锁后，执行一次 PostgreSQL clock_timestamp()，再验证 status、owner、version、expiry > now。等于 expiry 即过期。now()/CURRENT_TIMESTAMP 是事务开始时刻，不能用于这个检查。heartbeat 的新 expiry 从锁后的授权时刻加续约时长计算。

生产装配使用数据库时间；显式 Clock 仅为确定性测试接缝。exact-equality 测试使用真实数据库和注入的精确时刻，其余锁等待测试使用真实服务器时钟。该合同不承诺授权后的事务每个微秒都早于 expiry，也不防止数据库系统时钟向后跳变。事务内不进行模型或外部 HTTP 调用。

## 2. 实际事务入口与锁序

阻塞锁的共同顺序为 Tenant → 可选 Experiment → Run（ID 排序）→ Job（ID 排序）→ Attempt。父级不存在或不需要的路径可以省略。SQLAlchemy key_share=True、read=False 对应 NO KEY UPDATE；同时 read=True 才是 KEY SHARE。

| 入口 | 实际保护与取时 | 注意 |
| --- | --- | --- |
| heartbeat | Job NO KEY UPDATE → clock_timestamp → fenced UPDATE | 不再取得 Run，不形成反向父锁 |
| success / failure | Tenant KEY SHARE → Run NO KEY UPDATE → Job UPDATE → Attempt UPDATE → DB 当前时刻 | 保留 owner/version/state/expiry；结果、attempt、outbox 同事务 |
| reaper | 有限未锁身份发现 → 排序 Tenant KEY SHARE → Run NO KEY UPDATE SKIP LOCKED → Job UPDATE SKIP LOCKED → Attempt → DB 当前时刻 | 发现不是授权；上限 1000，繁忙 Run 留到下一批 |
| aggregate_run_in_session | Run NO KEY UPDATE | 不改键，避免持 Job 再升级到与 FK 冲突的强锁 |
| managed claim | 既有候选 Job 后，Experiment 与 Run 只用 SKIP LOCKED 的非阻塞 admission | 这是显式非阻塞例外，不宣称所有路径都先锁父；忙则放回重试 |
| ordinary claim | QUEUED Run 用 NO KEY UPDATE SKIP LOCKED；RUNNING Run 用 KEY SHARE SKIP LOCKED | 前者保护状态更新，后者预先取得 outbox FK 所需保护，保持同租户并行 |
| cancel | 沿既有父 Run → Jobs 路径 | 新 claim guard 避免普通 Run 与取消形成 Job→Run 阻塞环 |
| outbox | 既有事务内写入、异步 dispatcher | 本轮未改 dispatcher 租约；未复现的 token 风险不宣称解决 |

原版在真实 PG 固定屏障下出现 reaper/commit 死锁；补丁期间又复现普通 Run 的 claim/cancel 两种死锁（首次更新 Run 与 RUNNING 状态隐式 FK 锁）。新增非阻塞父保护修复后，仍运行既有同租户并发和公平性测试，不靠关闭并发过关。固定 reaper/commit 排程重复 20 次；未运行额外随机交错 100 次，不把有限测试称作数学证明。

故障诊断保留 pg_stat_activity/pg_locks 快照和服务错误代码；不新增监控数据库。未增加生产 lock-wait/reaper-lag 时序指标，不宣称获得完整生产可观测性。额外锁与权威时间读取可能增加往返，未测得吞吐提升；历史 NEGATIVE_SCALING 保留。

## 3. 新旧评分必须能共存

| 身份 | 旧执行 | 新执行 |
| --- | --- | --- |
| result schema | evalops.experiment-result/1.0 或 /2.0 | /3.0 |
| citation scorer | evalops.citation-scorer/1.0 | /2.0 |
| local input snapshot | /1.0 | /2.0 |
| durable evaluator | product_qa_v2 / product_agent_v2，product-v2 | product_qa_v3 / product_agent_v3，product-v3 |
| worker observation / aggregation | /2.0 | /3.0 |

新准备器发 v3；旧 evaluator 注册保留；读取器按冻结版本分派。未知或混合版本拒绝。没有表迁移或旧 JSON 回填。

新 source identity 规则：

- 单个非空字符串 source_id 或 id：原样采用，不 trim、不 str 强转。
- 两键相同：接受；两键冲突：target_citation_invalid。
- 任一提供的键不是字符串，或为空/纯空白：target_citation_invalid。
- 两键都缺：unresolved，计入 precision 分母，不当成匹配。
- 重复相同 ID 去重；额外错误引用可能 recall=1、precision<1，这是合理差异。
- source_id_recall / source_id_precision 是来源标识匹配，不是 semantic_support。后者未实现，不输出伪分。

接线：ProviderResult.from_target → normalize_product_observation → score_product_case → shared aggregation → durable accepted observation → build_durable_report → export → verify_durable_bundle / load_evidence。每层带版本；失败留在计划分母中。

重要勘误：旧注册 evaluator 与诊断函数确有歧义，但旧完整 score_product_case 已用诊断 recall 覆盖注册分。因此不能把孤立函数反例说成所有旧完整任务都曾质量误放行。保留旧注册语义和旧报告，新增规则只作用于新版本。

## 4. 三种验证不是同一层

| 命令/入口 | 真实范围 |
| --- | --- |
| verify_product_experiment（local private） | LOCAL_PRIVATE_STRUCTURE_ONLY：结构、hash、绑定；不是完整重评分 |
| load_evidence / evaluation_workflow analyze（local private + 原始 dataset） | LOCAL_RECOMPUTED_NOT_PROVENANCE：版本化完整重算；不是来源认证 |
| product_experiment_client verify（durable private） | PRIVATE_RECOMPUTED：原始输入、accepted observation、共享聚合及 HTML 重算 |
| public 模式 | PUBLIC_PROJECTION_ONLY：脱敏投影/派生 HTML；无法重算未公开的 raw |
| 交付 ZIP hash | 字节完整性，不是独立来源签名或生产验收 |

长答案、Agent 矛盾终态是上一基线已经修复的能力；本轮在真实 HTTP→worker→PG→报告→离线验证中再次覆盖，不冒充本轮首次实现。合成演练的“平台按预期处理失败”不等于模型质量 PASS。
