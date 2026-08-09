# 根因与两阶段 fair claim 设计

## 1. 根因

current selector 把两个职责放进同一个 durable claim 事务：

1. 计算哪个 Tenant 应获得公平轮次；
2. 锁 Job、创建 attempt、写 lease/version/audit/outbox。

同时又在锁前把每 Tenant 候选裁剪到 `rank <= limit`。这形成两个独立瓶颈：

- **rank pruning**：被锁的 head Job 已经占据唯一候选，`SKIP LOCKED` 无法回填 J2；
- **Tenant hot row**：Tenant 行锁覆盖整个 durable claim 事务，同 Tenant 的 Job 即使彼此独立也
  被强制单通道。

20 次固定 retry 与 eligible probe 只能等待锁释放，不能增加候选集合或移除 Tenant 单点，因此
属于放大器而非根因修复。

## 2. 选择的设计：short fair-turn reservation

把一次 `limit=1` claim 分为两个提交边界：

### Phase A：公平轮次事务

- 从仍有 eligible jobs 的 Tenant 中选择下一公平轮次；
- 锁只覆盖 Tenant scheduling row；
- 更新语义明确的 `last_scheduler_turn_at`；
- 立即 commit；
- 不创建 attempt，不写 lease，不改变 Job/Run 状态，不发 progress event。

排序仍以 eligible head Job 的 priority 为第一关键字，再按
`last_scheduler_turn_at NULLS FIRST`、head created/id 做确定性排序。这样保留高优先级优先，
同时保证 20:1 场景的 Tenant B 最迟第二个轮次出现。

### Phase B：tenant-scoped durable Job claim

- 使用 Phase A 返回的 Tenant ID；
- 在该 Tenant 下按 priority DESC、created_at ASC、id ASC 选择 Job；
- `FOR UPDATE OF evaluation_jobs SKIP LOCKED`，只锁 Job；
- 被锁 J1 不会裁掉 J2，数据库可以继续扫描并回填下一个 unlocked Job；
- Job 状态、attempt_count、lease owner/expiry、version、JobAttempt、audit、outbox 保持在同一
  durable transaction 中原子提交。

Phase A commit 后到 Phase B 前崩溃，只会消耗一个公平轮次时间戳；Job 仍 eligible，且不会产生
幽灵 attempt/lease/result。下一 Worker 可以继续领取。

## 3. 字段语义与迁移

`last_job_claimed_at` 当前既被当成公平调度状态，又暗示 durable claim 已发生。两阶段后该名字会
错误表达 Phase A 的事实，因此迁移为 `last_scheduler_turn_at`，并重建对应 index。升级保留已有
时间值；降级可逆恢复旧列名。旧 migration 不改写，新建后续 migration。

## 4. 批量领取处理

首个性能 blocker 与正式 capacity 计划均为 `limit=1`。实现仍保持公共 `limit=1..100`：每个
batch slot 独立执行一个公平轮次和一个 durable Job claim，直到达到 limit 或确认无 eligible
jobs。这样不会在一个 Tenant 锁下包住整批，也不会破坏每个 Job 的 durable atomicity；代价是
大 batch 增加事务数，需在后续 capacity/targeted evidence 中如实记录，不能凭推测宣称更快。

## 5. 锁顺序

Phase A 只锁 Tenant，提交后释放；Phase B 只锁 Job，并可能条件更新 Run。两个阶段不同时持有
Tenant 与 Job，因此去掉当前 Tenant→Job 复合锁依赖。其他 heartbeat/result/reaper 路径仍以 Job
lease/version fencing 为事实来源。

## 6. 必须用测试证明的行为

1. RED-1：A 的未提交 claim 不阻止 B 领取 J2；
2. RED-2：J1 单独被锁时 B 领取 J2；
3. RED-3：Tenant 被另一短事务锁住时 claim bounded retry，锁释放后领取 J1；
4. 8 Worker/100 Job 的 unique claim、eligible-empty 与 retry/success 显著下降；
5. reservation 后崩溃不产生 JobAttempt、lease 或状态变化；
6. priority 不回退；20:1 Tenant B position <= 2；
7. 既有 lease/fencing/result/outbox correctness 全部保持。

## 7. 明确拒绝的替代方案

- 只增加 `_MAX_CONTENTION_RETRIES` 或缩短 sleep：不改变 rank pruning/hot row；
- 去掉 Tenant 锁但保留锁前 `rank <= 1`：RED-2 仍失败；
- 只扩大 per-Tenant rank 候选：RED-3 仍失败；
- 在 Phase A 提前创建 attempt/lease：reservation crash 会制造幽灵执行；
- 新增外部队列/协调基础设施：超出本次根因与授权边界。
