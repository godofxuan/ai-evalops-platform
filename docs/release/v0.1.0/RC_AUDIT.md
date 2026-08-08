# v0.1.0 Release Candidate evidence consistency audit

审计日期：2026-08-08（Asia/Shanghai）  
审计分支：`codex/evidence-gate-1`  
规划基线：`0d85905`  
审计冻结 HEAD：`0d859057d41b7609f91e2e0bc51ecae9575133d8`

> 最终更新（2026-08-09）：本文件前半部分保留的是 RC 开始时的审计快照。current-head 实验现已
> 全部完成；最终结论由 [RELEASE_DECISION.md](RELEASE_DECISION.md) 覆盖：correctness、fairness、
> capacity、CI 与 manifest 均 PASS，但 formal performance gate FAIL，因此状态为 `NOT_READY`。

## 1. 修改前判断

本阶段先验证证据一致性，不先修改 scheduler、benchmark harness 或结果文档。原因是 release
claim 必须先区分三种不同时间和 source 的事实：

1. `15e7ac2e28b70430acd0bff88ee6cc78e5b86a86` 上完成的正式 32-arm load；
2. `03d6987c75f2169c8207f2355f1f9d7528f9d223` 上完成的 A–I reconnect/fencing After matrix；
3. `6d29925ac04601ac60a9eb5e2dfae3f0ad5dbca7` 上完成的小规模 tenant-fair claiming 合同。

第 1 项早于公平调度实现，因此只能是 historical pre-fair baseline。第 3 项证明当前公平策略的
受控 correctness，但不证明其大队列容量或当前-head 32-arm throughput。

## 2. Git 与环境冻结

初始工作树为空，当前分支和 HEAD 与规划基线一致。`0d85905..HEAD` 没有提交或文件差异，
因此没有 reset、rebase 或丢弃任何修改。

执行命令：

```powershell
git -c safe.directory='D:/文档/ai-evalops-platform' status --short
git -c safe.directory='D:/文档/ai-evalops-platform' branch --show-current
git -c safe.directory='D:/文档/ai-evalops-platform' rev-parse HEAD
git -c safe.directory='D:/文档/ai-evalops-platform' log -15 --oneline
git -c safe.directory='D:/文档/ai-evalops-platform' diff --stat 0d85905..HEAD
git -c safe.directory='D:/文档/ai-evalops-platform' log --oneline 0d85905..HEAD
```

结果：

- branch：`codex/evidence-gate-1`；
- HEAD：`0d859057d41b7609f91e2e0bc51ecae9575133d8`；
- worktree：clean；
- `0d85905 → current HEAD`：无差异，不影响实验设计；
- 本机仍没有可用 Docker CLI/daemon，真实 PostgreSQL/Compose 实验必须在已验证的 GitHub
  Actions Linux runner 上执行；本机 skip 或静态分析不能替代真实运行。

## 3. 已完整阅读的 release 输入

- `README.md`；
- `docs/resume_benchmark/README.md`；
- `docs/resume_benchmark/EXECUTION_LOG.md`；
- `docs/resume_benchmark/NEGATIVE_RESULTS.md`；
- `docs/resume_benchmark/EVALOPS_LOAD_REPORT.md`；
- `docs/resume_benchmark/EVALOPS_SCALING.csv`；
- `docs/resume_benchmark/LOAD_RESULTS.csv`（32 data rows）；
- `docs/resume_benchmark/EVALOPS_TENANT_FAIRNESS.md`；
- `docs/resume_benchmark/EVALOPS_CORRECTNESS_INVARIANTS.md`；
- `docs/resume_benchmark/RESUME_SAFE_METRICS.md`；
- `docs/resume_benchmark/EVALOPS_EVALUATOR_REGISTRY.md`；
- `app/jobs/claiming.py`；
- `app/persistence/orm_models.py`；
- `.github/workflows/ci.yml`。

相关 fairness/load/claim/concurrency 脚本、测试与 evidence workflow 的完整阅读在 release
contract 实现前继续进行；本审计不把“已发现文件名”误写成“已完整阅读”。

## 4. source、Actions 与 raw manifest 独立核验

### 4.1 Historical formal load

- source：`15e7ac2e28b70430acd0bff88ee6cc78e5b86a86`；
- Actions run：`31177702100`；
- run name：`Evidence Gate - Worker Scaling`；
- GitHub API：`completed / success / attempt 1`，head SHA 精确匹配；
- raw bundle：`docs/results/load/gate1-gh-31177702100-1/final/`；
- final manifest：`status=complete`，声明 664 files；
- 独立重算：expected 664、actual 664、file-set diff 0、SHA-256/size mismatch 0；
- arms：2 workloads × 4 worker counts × 4 repetitions = 32/32；
- measured Jobs：16,000 unique terminal successes；
- lost/failed/duplicate durable result/binding mismatch/collector gap：全部 0；
- aggregate quality gate：`VERIFIED`；adoption gate：`NOT_RUN`。

该证据可继续作为 VERIFIED historical pre-fair experiment，但不能称为 v0.1.0 current-release
capacity。

### 4.2 A–I reconnect and fencing After matrix

- source：`03d6987c75f2169c8207f2355f1f9d7528f9d223`；
- Actions run：`31247720668`；
- run name：`Evidence Gate - Fault Matrix`；
- GitHub API：`completed / success / attempt 1`，head SHA 精确匹配；
- raw bundle：`docs/results/fault/fault-gh-31247720668-1/`；
- manifest：5 expected files、5 actual files、file-set diff 0、SHA-256/size mismatch 0；
- report：27/27 records，9 scenarios × 3 repetitions，`status=verified`；
- lost、duplicate CaseResult、duplicate terminal commit、orphan running、invariant failure：全部 0；
- stale success：attempted 3、accepted 0；
- stale failure：attempted 3、accepted 0。

该证据支持 bounded reconnect/backoff、stop-aware wait 与 fencing correctness。它不支持
“exactly-once”或生产可靠性认证。

### 4.3 Tenant-fair claiming correctness

- implementation source：`6d29925ac04601ac60a9eb5e2dfae3f0ad5dbca7`；
- Actions run：`31253695011`；
- run name：`CI`；
- GitHub API：`completed / success / attempt 1`，head SHA 精确匹配；
- existing 10 Worker / 100 Job unique claim and fencing contract：PASS；
- controlled 20:1 fairness：legacy B position 21、fair B no later than position 2、first-wave
  duplicate 0。

这是受控 correctness/fairness proof，不是 1k/10k/100k queue capacity proof。

## 5. 一致性矩阵

| Claim | README/current docs | Raw/source/Actions | 审计状态 | 决定 |
|---|---|---|---|---|
| Historical 500-case/32-arm executed | load report 与 raw bundle 为 VERIFIED；README 历史表保留当时 NOT_RUN | 32/32 arms，664/664 hashes，run `31177702100` success | VERIFIED historical | 保留历史负面记录；修正 README 当前限制中的“仍未运行” |
| v0.1.0 fair scheduler 32-arm capacity | 尚无 current-fair source rerun | 当前 raw load source 是 pre-fair `15e7ac2…` | NOT_RUN | 不得复用旧数字作为 v0.1.0 throughput |
| Worker/Reaper bounded database reconnect | execution log 与 A–I After 为 VERIFIED；README 当前限制仍说“尚无策略” | source `03d6987…`，27/27，run `31247720668` success | VERIFIED scoped | 仅修正当前限制描述，不改写早期基线 |
| Fair scheduler controlled correctness | fairness doc 为 VERIFIED | source `6d29925…`，run `31253695011` success | VERIFIED scoped | 可作为 RC hard-correctness 输入 |
| Fair scheduler 1k/10k/100k capacity/query plan | fairness doc 明确尚未做 | 无 source-bound raw EXPLAIN/capacity bundle | NOT_RUN | 本阶段必须新增真实 PostgreSQL evidence |
| Stale success/failure rejection | A–I After 为 VERIFIED | attempted 3+3，accepted 0+0 | VERIFIED | 可作 correctness baseline；RC manifest 仍需绑定该证据 |
| Release readiness | 尚无 RC current-head capacity 或 release manifest | 不满足全部 release gate | NOT_READY | 当前唯一 blocker：current-fair source-bound capacity evidence 未运行 |

## 6. 发现的矛盾与修正规则

### 6.1 README 当前限制：formal load

README 的 2026-07-29、P2-7、P2-8、P2-9 时间点表格中的 `NOT-RUN` 是当时真实结果，已经
保留。README “当前限制”中已把过期的“正式 500-case/32-arm 仍未运行”修正为：历史
pre-fair formal load 已 VERIFIED；在本节记录的初始审计时，current fair RC source rerun 为
`NOT_RUN`，现已由第 9 节的最终 VERIFIED/性能 gate FAIL 结论覆盖。

### 6.2 README 当前限制：database reconnect

README “当前限制”原来写 Worker/Reaper “尚无优雅的数据库断线重连策略”，与
`03d6987…` 的 bounded reconnect/backoff 和 A–I After evidence 冲突。现已修正为：已有受控、
bounded、stop-aware reconnect/backoff；长期 outage、生产级连接治理和 SLO 仍未证明。

### 6.3 RESUME_SAFE_METRICS 的 source 边界

该文档中的正式 load 数字本身可追溯到 VERIFIED historical bundle；现已明确标识 pre-fair
exact source，避免读者把它理解为 current fair RC throughput。只增加了 source/time 边界，
没有改写已观测数字。

## 7. 审计期间遇到的问题与修正

1. 首次读取把 `EXECUTION_LOG.md` 和 `LOAD_RESULTS.csv` 错当成根目录文件。仓库索引确认
   它们位于 `docs/resume_benchmark/`；后续按真实路径重读。
2. 首次 `rg` 路径表达式只考虑 `/`，未匹配 Windows 的 `\`。改用 `rg --files -g`。
3. 一次并行读取输出被工具截断。被截断内容不计为“完整阅读”，随后按固定行段重读并核对
   `EXECUTION_LOG.md=623` 行、`LOAD_RESULTS.csv=32` data rows。
4. 首次独立 manifest 校验使用当前宿主不支持的 `.NET Path.GetRelativePath`。改用已解析基目录
   的安全前缀截取；load 最终得到 664/664、0 mismatch。
5. 首次 fault report 统计错误假设顶层字段名为 `records`。检查 schema 后改用 `results`，并按
   实际字段 `stale_result_accepted_count`、`stale_failure_accepted_count` 统计。
6. GitHub 网页抓取两个旧 run 出现 cache miss，本机也没有 `gh`。改用 GitHub public REST API
   只读核对全部三个 run。

这些问题都没有修改 raw evidence，也没有把失败命令伪装成成功结论。

## 8. 审计结论与下一步

当前结论：`NOT_READY`。

唯一 release blocker 是 current fair RC source 尚无 source-bound 的 1k/10k/100k fairness
capacity、真实 PostgreSQL EXPLAIN 和同协议 32-arm rerun。下一步先修正当前状态文档，再按
vertical TDD 建立 release/fair-capacity evidence contract；除非真实 paired evidence 发现并
定位 regression，不修改 production scheduler。

## 9. 最终审计收口（覆盖第 5、8 节的阶段性状态）

阶段性唯一 blocker“current fair evidence 未运行”已经关闭：

- fair capacity：source `9987a28…`，run `31272789199`，1k/10k 32/32、100k 16/16 VERIFIED；
- formal load：source `6acf72c…`，run `31274490704`，32/32、664/664、16,000 jobs VERIFIED；
- final fault：source `70a9b2b…`，run `31275450353`，A–I ×3、27/27 VERIFIED；
- CI：`31274490725` 与 `31275450358` success。

审计发现的新且最终唯一 blocker 是 performance release gate：相对 historical formal baseline，
8 个主要 workload/worker 中位数组有 5 个回退超过 15%。因此证据一致性已闭合，但 release decision
仍为 `NOT_READY`。详细数值、环境差异、失败历史和限制分别见本目录其余 release-facing 文档。
