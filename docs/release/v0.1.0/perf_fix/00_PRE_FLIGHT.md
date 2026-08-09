# Fair scheduler performance blocker sprint：pre-flight

记录时间：2026-08-09（Asia/Shanghai）  
执行分支：`codex/evidence-gate-1`  
起始 HEAD：`9b2e4a520387bf4a39db1ea5dcd265877a203b2e`

## 1. 本阶段目标与判断

当前 v0.1.0 RC 的 capacity、correctness、fault 与证据完整性均已闭合；唯一 release blocker
仍是 current fair scheduler 的 formal performance gate 失败。本阶段先修正 release-facing
百分比解释，再用真实 PostgreSQL 并发 RED 区分候选排名截断与 Tenant 热点行锁，只有复现后才
允许修改 production scheduler。

本阶段不扩展基础设施，不引入 Kafka、Celery、Temporal、Redis queue、RabbitMQ 或 Kubernetes；
不改写历史 raw evidence；不删除负面结果；不降低既有 release gate。

## 2. Git 与 PR 起始状态

- `git status --short --branch`：工作区干净，本地分支跟踪
  `origin/codex/evidence-gate-1`，无 ahead/behind 提示。
- 本地起始 HEAD：`9b2e4a520387bf4a39db1ea5dcd265877a203b2e`。
- GitHub PR：[#1](https://github.com/godofxuan/ai-evalops-platform/pull/1)。
- 2026-08-09 只读 REST 复核：`state=open`、`draft=true`、`mergeable=true`、
  `mergeable_state=clean`、base=`main`、head 精确等于起始 HEAD。
- 因 performance gate 仍失败，预检不把 PR 转为 ready，不创建 tag/release，不合并。

## 3. Actions 与 source 绑定复核

通过 GitHub public REST API 只读重查，不依赖 release 文档的转述：

| Evidence | Actions run | Exact source | API status |
|---|---:|---|---|
| historical formal load | `31177702100` | `15e7ac2e28b70430acd0bff88ee6cc78e5b86a86` | `completed/success`, attempt 1 |
| current-release fair capacity | `31272789199` | `9987a28d707653a45fffa60a283461e2514e3103` | `completed/success`, attempt 1 |
| current fair formal load | `31274490704` | `6acf72c3aa73c9fdc1664fe4e847fc8b8e90efd7` | `completed/success`, attempt 1 |
| final fault matrix | `31275450353` | `70a9b2b9d6d4cd7f42d7fa9654771a64e6d707b6` | `completed/success`, attempt 1 |

## 4. Raw manifest 独立重算

先用 PowerShell 独立枚举实际 payload，再逐文件重算 size 与 SHA-256；随后再调用项目 validator，
避免只相信 evidence generator 自己写出的状态。

| Bundle | File-set | SHA-256/size | Project validator |
|---|---:|---:|---|
| historical load final | 664 declared = 664 actual | 0 mismatch | complete, 32 arms |
| current fair load final | 664 declared = 664 actual | 0 mismatch | complete, 32 arms |
| fair capacity initial | 290 declared = 290 actual | 0 mismatch | VERIFIED, 32/32 arms, 0 blockers |
| fair capacity large | 146 declared = 146 actual | 0 mismatch | VERIFIED, 16/16 arms, 0 blockers |
| final fault | 6 declared = 6 actual | 0 mismatch | complete, 27 scenarios |

交叉计数结果：

- historical 与 current load 均为 32/32 valid arms，各 16,000 个 measured jobs；
- final fault 为 84 submitted = 84 unique = 84 completed；
- lost、duplicate CaseResult、duplicate terminal commit、orphan running、invariant failure 均为 0；
- stale success attempted/accepted 为 3/0；stale failure attempted/accepted 为 3/0。

## 5. 完整阅读边界与当前代码事实

已完整阅读 release decision、current-head load、capacity、correctness、negative results、environment、
execution log、CI workflow、claiming implementation、load/capacity harness、evidence validators、相关
claim/fairness integration tests、migration 与 Worker lease contract。

当前关键事实：

1. `build_claim_candidates_statement()` 先在 materialized CTE 中为每个 Tenant 排名，再在锁之前
   过滤 `tenant_candidate_rank <= limit`；当 `limit=1` 时，每个 Tenant 只保留一个候选。
2. 外层查询执行 `FOR UPDATE OF evaluation_jobs, tenants SKIP LOCKED`。
3. Tenant 的 `last_job_claimed_at` 与 Job 状态、lease、attempt、audit/outbox 在同一 claim 事务中更新。
4. `docs/05_worker_lease_contract.md` 的既有契约却明确写着锁只覆盖 Job 行，且同一 Run 的多个
   Job 可由不同 Worker 同时领取。当前实现与该契约存在需要用真实 PostgreSQL 判定影响的偏差。
5. current capacity harness 已记录 claim latency、empty claim 与 contention retry，但还不能完整
   区分 scheduler-turn transaction、job-claim transaction、eligible-empty 与 lock wait。

## 6. 假设优先级与可证伪预测

本轮最多验证三项，且初始只进入 H1：

1. **H1：排名截断 + Tenant 热点行锁的组合问题。**
   - 预测 A：事务 A 只锁 J1、不锁 Tenant 时，事务 B 的 fair selector 因锁前 `rank <= 1`
     看不到仍可领取的 J2。
   - 预测 B：事务 A 只锁 Tenant、Job 均未锁时，事务 B 仍无法领取该 Tenant 的任务。
   - 两项都出现才把组合 H1 标为 confirmed；只出现一项则标为 partial；均不出现则 rejected。
2. **H2：eligible probe + 固定重试放大。** 只在 H1 rejected/不足以解释现象时进入。
3. **H3：连接池、事务或数据库锁等待。** 只在前两项不足时，通过
   `pg_stat_activity`、`wait_event` 与 lock 视图验证。

生产代码保持不动，直到真实 PostgreSQL RED 稳定复现。

## 7. 预检过程中的问题与修正

1. 文件发现命令在没有 `glossary`/`AGENTS.md` 匹配时返回 exit 1；这是无匹配，不是测试失败。
2. 第一次手工 manifest 校验错误地把 Windows 路径替换写成双反斜杠，造成嵌套路径误报。
3. 第二次改用正则 `-replace`，但单个反斜杠是无效正则，产生大量工具错误；该结果作废。
4. 第三次改用 `String.Replace(char,char)` 并设置 `$ErrorActionPreference='Stop'`，load/capacity
   文件集合与哈希得到零差异；fault manifest 的 `files` 是数组而非映射，按真实 schema 单独
   验证后也得到 6/6、零差异。
5. 首次 load project-validator 单行命令因 PowerShell/f-string 引号嵌套而语法失败；后续命令
   成功会使同一 shell 最终退出 0，因此没有把批次总退出码当成 load 已验证。将 load validator
   单独重跑后，两份 bundle 均为 complete、32 arms。
6. GitHub 网页访问工具拒绝直接打开 REST API URL，本机也没有 `gh`；改用只读
   `Invoke-RestMethod` 查询公开 API，四个 run 与 PR 均成功复核。

所有上述错误都发生在临时只读检查命令中，没有改动历史 raw evidence 或 production code。

## 8. Pre-flight 结论

`PASS`，可以进入纯 evidence 百分比修正与 PostgreSQL RED 阶段。

Release 状态仍为 `NOT_READY`：预检证明证据完整，并没有解决 fair scheduler 的性能回退。
