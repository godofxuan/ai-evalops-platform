# Final scheduler qualification：pre-flight

记录时间：2026-08-09（Asia/Shanghai）

> 本文件是 sprint 开始时的不可变 pre-flight 快照，其中的 “current” 只指起始 source `2879b4c`，不代表
> 最终状态。最终状态见 `11_FINAL_DECISION.md`：Candidate 2 targeted 并发 20:1 公平门失败，release
> `NOT_READY`。

## 1. Git 与工作区

- 目标分支：`codex/evidence-gate-1`；
- current HEAD：`2879b4c71897720cd1820bab1594951589be9b6b`；
- remote tracking HEAD：`origin/codex/evidence-gate-1` 同为 `2879b4c…`；
- `git status --short --branch` 只显示分支跟踪关系，工作区无未提交修改；
- `git diff` 为空；
- 提示词观察起点 `2879b4c` 到 current HEAD 没有新增提交，因此不存在需要记录或保留的
  `2879b4c → current HEAD` 差异，也没有执行 reset/rebase。

起始 HEAD 之前与本次资格认证直接相关的提交依次为：

```text
45b987f fix(scheduler): serialize only short fair-turn reservations
ea1a8cb fix(scheduler): split fair turn from durable job claim
cad01c3 docs(scheduler): record contention root cause and design
95f64ea test(scheduler): capture same-tenant contention diagnostics
869b864 test(scheduler): isolate tenant hot-row contention
06f8e5e test(scheduler): isolate rank-pruning contention
8567738 test(scheduler): reproduce locked-head claim starvation
```

`45b987f` 的 blocking Tenant reservation 是已保留的失败 iteration；`2879b4c` 恢复了
`SKIP LOCKED` 的非阻塞 Phase A，但没有证明完整资格认证已经通过。

## 2. PR 与 GitHub Actions

本机没有 `gh` CLI，因此没有伪造 `gh pr view` / `gh run list` 的成功结果。改用 GitHub 公开 PR
与 Actions 页面只读复核：

- PR：[#1](https://github.com/godofxuan/ai-evalops-platform/pull/1)；
- 状态：open Draft；
- base：`main`；head branch：`codex/evidence-gate-1`；
- 标题仍为 `[Draft] v0.1.0 RC evidence - NOT_READY performance gate`；
- PR 正文仍停留在旧 formal/capacity/fault evidence，还没有当前 two-phase candidate 的最终资格证据。

最新四个相关 CI：

| Run | Event / source | Result | Duration | 关键事实 |
|---|---|---|---:|---|
| `31297535370` | push / `2879b4c` | cancelled | 6h00m19s | compose-smoke 通过；quality job 达 GitHub 6h 上限 |
| `31297538171` | PR / `2879b4c` | cancelled | 6h00m18s | 同一 source 的 PR workflow 也达 6h 上限 |
| `31297096663` | push / `45b987f` | cancelled | 6h00m18s | blocking Phase-A iteration 首次暴露无限等待 |
| `31297099741` | PR / `45b987f` | cancelled | 6h00m26s | 同一失败在 PR workflow 独立出现 |

`31297535370` 的公开 job detail 把取消位置标为 `step:17`。按 `.github/workflows/ci.yml` 的实际
step 顺序，第 17 步是 `Integration - same-tenant claim parallelism`。GitHub 未登录公开页面不能
读取完整日志，但“同一个测试 step 连续两个 source、push/PR 各自运行满 6 小时”已经证明当前测试
harness 缺少 fail-fast，不能把这些 run 解释为测试通过。

## 3. 六种状态的 pre-flight 判定

| 状态 | 判定 | 原因 |
|---|---|---|
| `WORKFLOW_EXECUTED` | PARTIAL | workflow 启动且 Compose job 通过，但 quality job 被 6h 上限终止 |
| `TESTS_PASS` | NO | same-tenant integration 没有产生通过结果 |
| `CORRECTNESS_PASS` | UNKNOWN | 卡死 source 没有完成相关 correctness suite |
| `EVIDENCE_COMPLETE` | NO | 缺 lock diagnostic、post-fix capacity/fault/formal bundle |
| `PERFORMANCE_PASS` | NOT_RUN | 当前 candidate 尚未获准进入 targeted benchmark |
| `RELEASE_READY` | NO | CI hang 是当前首要 blocker；历史 performance blocker 尚未重测 |

## 4. 当前源码事实与过期文档

当前 `app/jobs/claiming.py` 已不是历史上的“Job/Tenant 同事务联合领取”：

1. Phase A 用独立短事务选择 Tenant、更新 `Tenant.last_scheduler_turn_at`，当前显式锁为
   `FOR UPDATE OF tenants SKIP LOCKED`；
2. Phase B 用另一个事务执行 tenant-scoped Job selector，显式锁为
   `FOR UPDATE OF evaluation_jobs SKIP LOCKED`，并原子写 Job/Attempt/lease/version/Audit/Outbox；
3. Phase B 没有显式获取 Tenant scheduler row lock，但 tenant-referencing Audit/Outbox/Result
   writes 仍可能触发 PostgreSQL foreign-key lock semantics；
4. README Phase 3 仍写“同时锁定 Job/Tenant”，`SQLAlchemyJobClaimer` docstring 仍写“one short
   PostgreSQL transaction”，两处都落后于源码，需要在不改变 READY 状态的前提下修正。

## 5. 当前 CI hang 假设

排名最高、但尚未确认的假设为 `H2_FK_LOCK_INTERACTION`：测试事务 A 长期持有 Tenant
`FOR UPDATE`，事务 B 虽然只显式选择/锁 Job，但完整 durable claim 插入 `AuditEvent` 等带
`tenant_id` 外键的记录时需要 referential-integrity lock；B 等待 A，而测试的 A scope 又同步等待
B 返回，形成测试级 wait cycle。

可证伪预测：

1. selector-only 的 Phase-B SQL 在 Tenant `FOR UPDATE` 下仍能快速选中 Job；
2. 完整 durable claim 在相同强锁下以短 `lock_timeout` 失败，并由 `pg_stat_activity`、`pg_locks`
   与 `pg_blocking_pids` 指向 Tenant/FK 相关等待；
3. 把对照锁改为 `FOR NO KEY UPDATE` 后，完整 durable claim 可以 bounded completion；
4. `FOR NO KEY UPDATE` 仍使同一 Tenant 的两个 reservation writer 互斥，同时 `SKIP LOCKED` 允许
   第二个 Worker 调度其他 Tenant。

在取得上述真实 PostgreSQL 证据前，不修改 production lock mode。

## 6. 本机环境边界

- 系统 Python：3.14.3；项目使用仓库内 `.codex-tools/Scripts/uv.exe` 与锁定环境；
- Docker / Docker Compose：CommandNotFound；
- `psql`：不可用；
- 本机 TCP 5432：没有监听者。

因此本机可执行 unit/SQL compile/static tests，但不能把 integration skip 当作 PostgreSQL GREEN。
真实 lock evidence 与 concurrency GREEN 必须由 GitHub Actions 的 PostgreSQL 18.4 service 获取。

## 7. Pre-flight 决定

可以进入 fail-fast test contract 与 lock diagnostic；不允许进入 targeted/capacity/fault/formal
performance workflow。Release 保持 `NOT_READY`，当前首要 blocker 是 same-tenant integration
无限等待及其尚未被数据库证据解释的锁交互。
