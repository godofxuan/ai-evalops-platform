# v0.1.0 Release Candidate execution log

本日志记录每一步的判断、命令、失败、修正、效果和边界。历史失败保留，不因后续 GREEN
删除。

## 2026-08-08 — Source freeze and evidence consistency audit

### 修改前判断与原因

规划基线 `0d85905` 与初始 HEAD
`0d859057d41b7609f91e2e0bc51ecae9575133d8` 相同，工作树 clean，因此不 reset。先核对
README、resume-safe 文档、raw bundle、source commit 和 Actions，避免把 pre-fair 性能误写成
current-release capacity。

### exact commands

```powershell
git -c safe.directory='D:/文档/ai-evalops-platform' status --short
git -c safe.directory='D:/文档/ai-evalops-platform' branch --show-current
git -c safe.directory='D:/文档/ai-evalops-platform' rev-parse HEAD
git -c safe.directory='D:/文档/ai-evalops-platform' log -15 --oneline
git -c safe.directory='D:/文档/ai-evalops-platform' diff --stat 0d85905..HEAD
git -c safe.directory='D:/文档/ai-evalops-platform' log --oneline 0d85905..HEAD
```

另用 PowerShell `Get-FileHash -Algorithm SHA256` 独立重算 load final manifest 的 664 个 payload
和 fault manifest 的 5 个 payload；用 GitHub public REST API 查询 Actions run。

### 问题与修正

1. 首次假设两个文档位于仓库根目录；索引后改用 `docs/resume_benchmark/`。
2. 首次 `rg` 表达式未考虑 Windows `\`；改用 filename glob。
3. 一次大输出被截断；截断段不算已读，按固定行段重读。
4. 当前 PowerShell/.NET 没有 `Path.GetRelativePath`；使用已解析基目录的安全前缀截取。
5. fault report 顶层数组名是 `results` 而非假设的 `records`；检查 schema 后按真实字段重算。
6. 两个旧 Actions 网页抓取 cache miss；改用 public REST API。

### 结果、Actions 与 raw artifact

- load：source `15e7ac2e28b70430acd0bff88ee6cc78e5b86a86`，run `31177702100`，
  `completed/success`，664/664、file-set/hash/size mismatch 0；
- fault After：source `03d6987c75f2169c8207f2355f1f9d7528f9d223`，run `31247720668`，
  `completed/success`，27/27、stale success/failure accepted 0/0；
- fairness：source `6d29925ac04601ac60a9eb5e2dfae3f0ad5dbca7`，run `31253695011`，
  `completed/success`，legacy B=21、fair B<=2、first-wave duplicate=0。

审计提交：`a4abe5a docs(release): audit v0.1.0 evidence consistency`。

文档边界修正提交：`4f0a65b docs(evidence): correct current release boundaries`。只修 README
当前限制和 resume-safe source 边界；历史日期表、负面记录、原始数字均未改写。

### 效果与限制

旧 32-arm 现在被明确限定为 VERIFIED historical pre-fair baseline；当前 fair RC 的大队列与
32-arm 仍是 `NOT_RUN`。resume-safe claim 仅增加 source 边界，没有新增性能数字。

## 2026-08-08 — Release evidence contract RED

### 修改前判断

现有 Gate 1 能验证 source、arm、correctness、collector 和完整 final manifest，但其历史 schema
把缺 arm 标为 `UNKNOWN`，且没有 release-scope、raw EXPLAIN、stale success/failure 独立字段。
直接改变历史 Gate 1 语义会破坏既有证据解释，因此新增 release-level contract。

### RED

新增 `tests/unit/scripts/test_release_evidence.py`，包含 15 个行为测试；manifest mismatch 使用
参数化分别覆盖 hash 和 file-set。覆盖用户要求的 14 项，并额外要求完整 source-bound bundle
才能 `VERIFIED`。

exact command：

```powershell
$env:UV_CACHE_DIR='D:\文档\ai-evalops-platform\.codex-tools\uv-cache'
& '.\.codex-tools\Scripts\uv.exe' run --no-sync pytest tests/unit/scripts/test_release_evidence.py -q
```

结果：exit `2`，collection error：
`ModuleNotFoundError: No module named 'scripts.release_evidence'`。这正是预期 RED，说明测试先于
实现；尚未产生任何 GREEN 或真实实验 claim。

### 实现、第二个 RED 与 GREEN

新增 `scripts.release_evidence.assess_release_bundle`。公开入口会：

- 重算 manifest 的完整 payload file set、size 与 SHA-256；
- 要求 40 位 exact source commit，并区分 `current_release_capacity` 与
  `historical_baseline`；
- 从 CSV 检查 expected/missing/duplicate/unexpected arms；
- 检查 submitted/unique/terminal、lost、duplicate durable result、stale success、stale
  failure、illegal transition 和 orphan nonterminal；
- 要求真实 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` payload，缺失时不能 VERIFIED。

第一次实现后 16 tests passed。代码复核发现 manifest payload digest 的 schema 条件可能接受
40 位字符串，于是先新增回归测试。第二次 RED 为 `1 failed, 16 passed`：错误只被归为 hash
mismatch，而未被 schema 拒绝。最小修正把 payload digest 严格限定为 64 位小写 SHA-256，
source commit 的 40 位规则保持独立。

最终 exact command：

```powershell
uv run --no-sync pytest tests/unit/scripts/test_release_evidence.py -q
uv run --no-sync ruff format --check scripts/release_evidence.py tests/unit/scripts/test_release_evidence.py
uv run --no-sync ruff check scripts/release_evidence.py tests/unit/scripts/test_release_evidence.py
uv run --no-sync mypy scripts/release_evidence.py
```

结果：`17 passed`；format passed；Ruff `All checks passed!`；strict MyPy `Success`。首次聚合检查
曾因 Ruff `SIM114` 失败，按建议合并两个同体分支后重跑四项全部 GREEN。

当前效果仅是 fail-closed release admission contract；尚未生成大队列数据、EXPLAIN 或 current
32-arm evidence，因此 release 状态仍是 `NOT_READY`，resume-safe claim 不变。

## 2026-08-08 — Fair-capacity harness 与远程 RC 工作流

### 先判断范围与测量口径

本阶段没有修改生产调度 SQL。原因是当前任务首先要求测量 current fair scheduler，且尚无
可证明的性能回归足以授权修改生产算法。实验拆成两层：

1. 在同一 PostgreSQL `REPEATABLE READ` transaction snapshot 中，交替执行 current fair
   selector 和只用于 benchmark 的 legacy global FIFO selector，各重复 4 次，保存原始
   `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`；
2. 每个 arm 在仍有大队列 backlog 时，用真实 `EvaluationWorker`、
   `SQLAlchemyJobClaimer`、heartbeat、result/failure committer 完成固定 500-job sample。

这意味着 `queue_size` 是候选队列规模，`sample_jobs=500` 是真实处理样本，不能把它解释成
“完整排空 100k 队列的吞吐”。资源口径是一个 benchmark 进程内运行多个真实 Worker 对象，
不是多个 Compose Worker 容器的总 RSS；该限制写入 configuration，而不隐藏。

计划固定为：queue 1k/10k/100k × single tenant / balanced multi-tenant / 20:1 skew /
many-small-tenants × Worker concurrency 1/2/4/8 × production claim batch 1，共 48 arms。
初始阶段先跑 1k/10k 的 32 arms，只有它的 assessment 为 VERIFIED 才进入 100k 的 16 arms。

### TDD：计划、分布、旧基线、EXPLAIN 与 manifest

先新增 `tests/unit/scripts/test_fair_capacity_evidence.py`，在实现文件不存在时执行：

```powershell
uv run pytest tests/unit/scripts/test_fair_capacity_evidence.py -q
```

首次 RED 是 import/collection failure，证明测试先于实现。随后按垂直切片逐一实现：

- `build_fair_capacity_plan`：初始阶段恰好 32 arms，batch 固定为 1；
- `tenant_job_counts`：总数精确守恒，balanced=4 tenants，20:1 误差限制在 19–21，
  many-small=100 tenants；
- `build_legacy_fifo_statement`：只复刻 pre-fair global priority/created/id FIFO，保留
  eligible job/run 与 `FOR UPDATE ... SKIP LOCKED`，不进入生产路径；
- `summarize_explain`：提取 planning/execution time、root rows/loops、shared/temp blocks、
  WindowAgg candidate cardinality、sort 与磁盘 spill，不虚构 PostgreSQL CPU；
- `queue_sizes_for_stage`：100k 阶段要求前置状态精确为 VERIFIED；
- `write_release_manifest`：exact source、完整 fileset、size、SHA-256、拒绝覆盖与 symlink。

这一批最初为 8 tests passed。第一次聚合质量门禁结果是：pytest 通过，但 Ruff format、Ruff
check 和 strict MyPy 失败。问题包括 2 个未格式化文件、unused import、async function 中同步
文件/子进程调用、可合并 context manager、4 个类型错误。处理原则是：机械格式交给 Ruff，
语义问题用小补丁处理；最终没有用 `# noqa` 大范围屏蔽规则。

### 问题：多 Worker 局部列表会伪造领取顺序

第一次实现把每个 claimer 的 `claimed_jobs` 按 Worker 列表拼接。这样 Worker A 的全部领取可能
被排在 Worker B 前面，即使 B 实际更早完成，`tenant_first_claim_positions` 会失真。先增加
`test_order_timed_values_uses_global_event_time_not_worker_list_order`；RED 为无法 import
`order_timed_values`。实现后，每次 claim 返回时记录全局 monotonic `perf_counter`，汇总所有
Worker 事件后按时间排序。

首次 GREEN 尝试又暴露 `Sequence` 漏导入，以及 Ruff `UP047` 要求 Python 3.12 PEP 695
泛型语法；修正为原生 type parameter 并显式标注 `list[ClaimedJob]` 后，结果为 9 passed、
format/ruff/mypy 全部通过。

### 每个 arm 的 fail-closed 判定

仅有 bundle 总合同不足以证明 arm 本身正确，因此先写 RED 测试，要求：

- submitted = unique = terminal = claimed = sample；
- lost、duplicate durable result、orphan nonterminal、attempt sequence mismatch、stale
  accepted、illegal transition 全部为 0；
- 20:1 skew 的 secondary tenant 必须在前 2 个 claim 内出现；
- 预期 tenant 不能从固定 sample 中消失。

RED 为无法 import `assess_arm_runtime`。第一次实现后的“合法样本”测试失败，因为测试夹具没有
显式提供 stale/illegal 三个字段；实现把缺失字段视为 UNKNOWN/非零并拒绝是正确行为，所以补
完整夹具，而没有放宽校验器。最终 12 passed，static gates 全绿。运行器会先把 raw runtime 与
arm assessment 写盘，再在 FAILED 时抛出错误，因此失败数据仍被保留，manifest 不会伪装完整。

20:1 arm 同时记录 fair 实测 secondary position 和 legacy FIFO 按 fixture 排序得到的基线
position。stale success/failure 不是每个 capacity arm 重复注入，而是明确引用 source
`03d6987c75f2169c8207f2355f1f9d7528f9d223` 的 A–I After fault bundle；CSV 与 configuration
都标为 `referenced_fault_after_bundle_not_induced_per_arm`，避免把引用证据写成当场测量。

提交前交叉核对发现，初稿误把该 source 写成不存在的 `03d6987e071...`。执行 `git cat-file -t`
后，错误候选 exit 128；正确的 `03d6987c75...` 是 commit，且与 fault manifest、report、
environment/source.txt 全部一致。根因是工作中转摘要抄写漂移。修正时把常量移到可单测的
`fair_capacity_evidence` 模块，并新增 exact-SHA 回归测试，避免以后再次静默引用错误对象。

### CLI 入口问题

执行：

```powershell
uv run python scripts/run_fair_capacity_test.py --help
```

失败为 `ModuleNotFoundError: No module named 'app'`。原因是直接运行文件时 Python 把
`scripts/` 而非仓库根目录作为首个 import path。没有用运行时 `sys.path` 注入掩盖它，而是按
仓库既有规范使用模块入口：

```powershell
uv run python -m scripts.run_fair_capacity_test --help
```

结果 exit 0，CLI 参数完整显示。正式 workflow 只使用该模块入口。

### 远程工作流的 RED→GREEN

新增工作流合同测试，先要求以下步骤存在并有正确顺序：Compose 启动 PostgreSQL/Redis、
Alembic migration、1k/10k、100k、always diagnostics/upload/commit。首次 RED 为 workflow
文件不存在，2 failed。实现 `.github/workflows/release-candidate-evidence.yml` 后第一次测试仍
失败，因为测试错误地要求迁移命令包含字面量 `migrate`，而真实标准命令是
`uv run --no-sync alembic upgrade head`；修正测试去验证实际迁移动作。随后 14 个相关测试
通过。另有 Ruff `I001`，由 Ruff 只整理 import block 后通过。

工作流用 `$GITHUB_SHA` 绑定 exact source；生成
`docs/results/release/v0.1.0/rc-gh-<run>-<attempt>/` 不可变目录；初始命令失败会自然阻止下一
个普通 step，因此 100k 不会越过 gate。diagnostics、artifact upload 和 git commit 使用
`always()`，失败时也保存 partial evidence。最后才 `docker compose down --volumes`。

最终 diff 复核又发现，最初 `queue_sizes_for_stage` 虽有单测，却没有接入 CLI，100k 只靠 YAML
step 顺序保护，手工调用仍可绕过。先把 workflow contract 改为要求 `--stage initial/large` 与
`--prior-assessment`，RED 为 1 failed；随后让 CLI 读取 initial assessment，并同时验证
`status=VERIFIED`、source SHA 与本次完全相同、requested queue sizes 与 frozen stage plan 完全
相等。initial stage 也拒绝携带 prior assessment。新增同源通过、异源拒绝和计划外 queue 拒绝
测试后，100k gate 从“编排约定”变成运行入口本身的 fail-closed contract。

### 再次加固离线 admission contract

代码复核发现三个“运行时能拦，但离线重验可能漏掉”的缺口，均先制造 RED：

1. `attempt_sequence_mismatch_count=1` 原先仍被判 VERIFIED：RED 为 `1 failed, 17 passed`；
   将该列加入 required counts，并新增 `attempt_sequence_mismatch` blocker。
2. skew secondary position=3 原先仍被判 VERIFIED：新增 distribution、fair/legacy secondary
   position 必填列，fair >2 为 `skew_fairness_regression`，legacy <=2 为
   `legacy_fifo_baseline_invalid`。
3. 原合同只要存在一份 raw EXPLAIN 就可能通过：新增精确覆盖合同，正式调用要求每个 arm 的
   fair/legacy × repetitions 1..4 集合完全一致，缺失、重复或意外记录均为
   `postgres_explain_coverage_mismatch`。RED 首先表现为入口没有
   `expected_explain_repetitions` 参数；实现后又增加完整 8-record 正向测试，证明不是永远失败。

最终相关命令与结果：

```powershell
uv run pytest tests/unit/scripts/test_release_evidence.py `
  tests/unit/scripts/test_fair_capacity_evidence.py `
  tests/unit/scripts/test_release_candidate_workflow.py -q
uv run ruff format --check scripts/release_evidence.py scripts/fair_capacity_evidence.py `
  scripts/run_fair_capacity_test.py tests/unit/scripts/test_release_evidence.py `
  tests/unit/scripts/test_fair_capacity_evidence.py `
  tests/unit/scripts/test_release_candidate_workflow.py
uv run ruff check <同一文件集合>
uv run mypy --strict scripts/release_evidence.py scripts/fair_capacity_evidence.py `
  scripts/run_fair_capacity_test.py
```

结果（加入 fault source 与 stage-binding 回归后）：`38 passed`；Ruff format/check 通过；strict MyPy
通过。

### 当前效果与仍未完成的证据

本地环境没有 Docker，因此此处只证明 harness、SQL shape、合同和工作流静态正确，不能声称
真实 PostgreSQL 1k/10k/100k 已运行。下一步必须提交并推送这一小目标，触发 GitHub Actions；
只有远程 initial 与 large bundle 均 VERIFIED、原始 plans/CSV/manifest 可独立重算后，才能
继续 current-head 32-arm protocol 和最终 release decision。此时 release 仍是 `NOT_READY`。

### 提交前全仓回归

```powershell
uv run pytest -m "not integration" -q
uv run ruff format --check .
uv run ruff check .
uv run mypy app scripts tests/integration tests/concurrency
```

第一次结果：`610 passed, 13 deselected in 365.07s`。接入 CLI stage binding 后重新完整执行，
最终结果为 `612 passed, 13 deselected in 359.13s`；315 files already formatted；Ruff all checks
passed；MyPy 133 source files 无问题。13 个 deselected 是带 `integration` marker、需要真实外部服务
的测试，并非失败或被静默跳过。真实 PostgreSQL/Compose capacity 运行仍由随后 GitHub Actions
负责，不能用这 610 个本地测试替代。

## 2026-08-08 — 首次远程 RC 失败与 result commit deadlock 修复

### 原始远程反馈环

推送 source `3170dbcdd6b84135103682e7dd6f40f148d73328` 后，GitHub Actions run
`31260188889` 成功完成 checkout、依赖、Compose PostgreSQL/Redis 和 Alembic migration，随后
在 initial 1k/10k step 失败。100k step 被正确 skip；diagnostics、artifact upload、失败证据
commit 和 Compose cleanup 全部成功。bot evidence commit 为 `95c0799`。

拉取证据后确认：

- `fair-q1000-single_tenant-w1-b1` 完成 500/500，lost/duplicate/orphan/attempt mismatch 均为
  0，arm assessment VERIFIED；
- 双 Worker arm 已生成 8 份真实 EXPLAIN，但尚未生成 runtime raw；
- `failure.json` 为 `OperationalError`；
- PostgreSQL compose log 在 2026-08-08 13:44:24 UTC 明确记录 deadlock：process 686 等待
  transaction 1808，process 685 等待 transaction 1807，双方都在
  `SELECT evaluation_runs ... FOR UPDATE OF evaluation_runs`。

因此失败不是文件合同、Compose 或资源 collector 造成，而是真实 Worker 并发 result commit
路径的数据库死锁。失败 evidence 保留不改写，release 继续为 NOT_READY。

### 假设、最小化与根因

按 `diagnose` 流程列出并检验四个假设。最终证据支持：两个 transaction 各自先锁自己的 Job，
向 `case_results` flush 时因外键分别持有同一 Run row 的 KEY SHARE，之后
`aggregate_run_in_session` 都尝试升级为 Run `FOR UPDATE`，形成对称锁升级环。claim queued→running
竞争、其他 run→job 路径和 collector 假设均与“双方 context 都是 evaluation_runs”不符。

现有 PostgreSQL concurrency test 创建了 100 个同 run claims，却只串行提交第一个结果，因此
没有覆盖真实模式。先把前两个 claim 改为 `asyncio.gather(commit_success, commit_success)`，并把
后续 reaper 期望从 99 调整为 98。该测试需要远程 migrated PostgreSQL，本地不能伪造其 RED；
原始 RC run 的 deadlock graph 是当前真实反馈环与失败证据。

### 最小生产修复

新增 `build_run_lock_for_completion_statement` 的单元 RED；首次运行 collection error，因为入口
尚不存在。实现后，`SQLAlchemyResultCommitter.commit_success` 在 transaction 开始时先
`FOR UPDATE OF evaluation_runs`，再验证并锁 owned Job，之后才 flush CaseResult/Attempt/Audit 与
执行聚合。canonical order 由原来的 `job/FK-key-share → run upgrade` 改为明确 `run → job`。

这是 result commit 锁序修复，不修改 fair claim scheduler。代价是同一 Run 的 result completion
从 transaction 开始即串行；但原聚合本来就必须串行锁同一 Run，因此没有新增跨 Run 串行化。
局部结果：2 unit tests passed；Ruff passed；strict MyPy passed。真实结论必须由更新后的并发
integration test 和原始 RC workflow 重跑给出，因此新增
`.github/release-candidate-trigger.txt` 触发下一次 source-bound run。

### 修复后的本地回归

第一次全仓非集成回归为 `1 failed, 612 passed, 13 deselected`。唯一失败不是状态机或锁语义，
而是 `test_outbox_enqueuing.RecordingSession` 测试替身没有实现真实 `AsyncSession.scalar`，在新
run-first lock 调用处产生 `AttributeError`。补齐 fake 的 scalar 结果队列，并显式加入
`RUN_ID` 作为第一项后，相关 7 tests passed。

再次从最终工作树完整执行：

```powershell
uv run pytest -m "not integration" -q
uv run ruff format --check .
uv run ruff check .
uv run mypy app scripts tests/integration tests/concurrency
git diff --check
```

结果：`613 passed, 13 deselected in 361.11s`；315 files formatted；Ruff passed；MyPy 133
source files passed；diff check passed。真实双提交 integration test 在本地仍因无 Docker/PostgreSQL
被 marker 排除，必须以接下来的 GitHub CI 与 RC workflow 为最终反馈环。

## 2026-08-08 — 第二次远程 deadlock：统一 Tenant → Run → Job

### 第二次 RED 证据

修复 source `feb4de1bae2cec1dd6d3c0158dc8efd4a25f559e` 触发 RC run `31261077382`
与 CI run `31261077379`。RC 仍在双 Worker arm 失败，100k 再次被 gate skip，failure evidence
commit 为 `9b91ab1`。标准 CI 的 compose-smoke 成功，但真实 PostgreSQL
`Integration - job claiming, trace propagation, and lease fencing` 失败，证明新增并发 test 是独立
有效的 RED seam。

新的 `failure.json` 精确为 `DeadlockDetected`，PostgreSQL graph 与第一次不同：

- process 672 在 INSERT `audit_events` 的 tenant FK KEY SHARE 上等待 process 673；
- process 673 在 INSERT `progress_event_outbox` 时反向等待 process 672；
- context 明确为 relation `tenants`，随后 cleanup DELETE 与尚未结束的 Worker 又产生第二个干扰性
  deadlock。

这证明 run-first 修复消除了第一次 Run lock-upgrade 环，但 completion 仍是 `Run → Tenant FK`，
而 claim path 是 `Tenant FOR UPDATE → Run`，锁序依旧相反。

### 第二层修复与 harness 清理

先新增 tenant-lock SQL 单元 RED，collection error 表明 helper 尚不存在。随后新增
`build_tenant_key_share_for_completion_statement`，使用 PostgreSQL
`FOR KEY SHARE OF tenants`；result transaction 的显式顺序变成：

1. Tenant KEY SHARE；
2. Run FOR UPDATE；
3. owned Job FOR UPDATE；
4. CaseResult/Audit/Outbox flush 与 Run aggregation。

KEY SHARE 可在多个 completion 间兼容，因此不会把同一 Tenant 下不同 Run 的所有结果提交独占
串行；但它会在任何 transaction 持 Run 前与 claim 的 Tenant UPDATE 锁完成排序，从而消除
Tenant↔Run 环。

同时把 harness 的 Worker `asyncio.gather` 改为 `asyncio.TaskGroup`。任一 Worker 抛错时，其余
Worker 会被取消并等待退出，之后才 dispose engine 与删除 fixture，避免 failure cleanup 和仍活跃
transaction 交叉制造第二个 deadlock。局部验证为 23 tests passed，Ruff/MyPy passed。下一次
push 需要同时让真实 integration RED 转 GREEN，并让原始 RC 走过双 Worker arm，才能接受修复。

提交前最终本地结果：`614 passed, 13 deselected in 369.80s`；315 files formatted；Ruff
passed；MyPy 133 source files passed；diff check passed。integration marker 的真实结论仍未提前
声称为 GREEN。

## 2026-08-08 — 第三次 CI：统一 cancellation 锁序

第三次 source `2a76c74721ae4aae4b9c08f59c7e19467942d13e` 的 RC run `31261616628`
越过前两次约 63 秒的双 Worker deadlock 点并持续运行 initial，说明 capacity 主路径锁环已解除。
但标准 CI run `31261616651` 的真实 job-claiming integration 仍失败。

公开 Actions summary 的 annotation 显示，新加的两个并发 result commit 已通过；失败发生在同一测试
后半段既有 `cancel_run` 与 `commit_success` race，`race_outcomes` 中出现 BaseException。源码核对
确认 cancellation 仍采用 `Jobs FOR UPDATE → Run FOR UPDATE`，与 result 的
`Tenant → Run → Job` 相反。

保持原断言“双方均不得抛异常”不变，先新增 cancellation tenant lock SQL 单元 RED；collection
error 后实现 `build_tenant_key_share_for_cancellation_statement`，并把 cancellation transaction
重排为：初读 tenant-scoped Run → Tenant KEY SHARE → Run FOR UPDATE → 按 ID Jobs FOR UPDATE →
flush/aggregate。这样 cancellation、result completion 与 claim 都遵循 Tenant → Run → Job(s)。

两个 outbox unit test 的 RecordingSession 结果队列同步改为真实调用顺序，没有屏蔽异常。局部
16 tests passed，随后全仓结果为 `615 passed, 13 deselected in 372.41s`；315 files formatted；
Ruff passed；MyPy 133 source files passed；diff check passed。更新 trigger 后必须再次让真实 race
integration 转 GREEN；此前 source 的运行结果不外推到新 source。

## 2026-08-08 — 用实测结果校正 fixed-sample 协议

第三次 RC 的 500-job 协议在 initial 持续超过 25 分钟仍未完成。第一份已保存 raw 显示 q1k、
single Worker 的 500 jobs 需要 60.43 秒（8.27 jobs/s），而 fair selector 每次 claim 都要在当前
queue 上执行候选排名；因此把固定 500 claims 原样扩到 q10k/100k × 48 arms，100k 很可能触及
workflow 240 分钟上限。这是协议可执行性风险，不是生产 correctness 失败。

先把 workflow contract 改为要求 `--sample-jobs 100`，RED 为 1 failed。随后把 CLI default 和
initial/large 命令都改为 100。100 不是任意缩小：many-small 分布精确为 100 tenants，sample
仍能验证每个 tenant 至少一次；p50/p95/p99、throughput、CPU/RSS、connections、lock waits 和
20:1 secondary position 仍可计算。口径继续明确为“在大 backlog 下完成固定样本”，不宣称完整
排空吞吐。历史 500-job 失败 raw 保留，不改写。

本机没有 `gh` CLI。检查命令因 PowerShell `$LASTEXITCODE` 沿用旧值一度输出 version/auth=0，
但实际两次均为 CommandNotFound；没有读取 Git credential 或绕过 GitHub 权限取消 run。新 push
只会按既有 concurrency 规则替换 pending run，不取消仍在运行的旧 evidence。

旧 500-job run 长时间占用原 concurrency group，导致 current 100-job run pending。先新增 workflow
contract，要求 group 精确为 `release-candidate-fair-capacity-v2`；RED 为 1 failed。更新 group 后，
current protocol 可使用独立 runner 立即验证，不删除或改写旧 run。旧 pending/旧 source 以后若
执行，其 Git push 仍受 non-fast-forward 保护，不能覆盖当前分支；artifact 保留其独立价值。

## 2026-08-08 — v2 容量首跑：初始门通过，100k w4 失败，补齐异常证据

### 修改前判断与真实执行

source `05dc5264545df0714fa0918818c6383ee7eb3403` 同时触发标准 CI run
`31262849255` 与 RC capacity run `31262849253`。标准 CI 的 `compose-smoke`、
`quality-and-integration` 均为 success，说明当前 source 的常规单测、真实 PostgreSQL 集成、
Compose 启动和镜像构建没有回归。RC run 使用独立 v2 concurrency group，未被仍在运行的旧
500-sample run 阻塞。

RC run 在 12m30s 后 failure，但 always-preserve 路径按设计执行：artifact
`rc-gh-31262849253-1` 大小 809 KB，GitHub artifact digest 为
`sha256:400422753144086ff2395420f2f48ac4ab1fac0ccd2d74266eab533f54a5bd99`，失败证据提交为
`9c3e152`。没有删除、覆盖或把该失败改写成成功。

### 已经成立的效果与尚未成立的结论

`initial/assessment.json` 是 `VERIFIED`：expected/observed 均为 32 arms，source 与 expected
source 均精确为 `05dc526...`，1k/10k 无 missing、duplicate、unexpected arm，每臂 fair 与
benchmark-only legacy FIFO 各保存 4 次真实 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`，manifest
scope 为 `current_release_capacity` 且 blockers 为空。因此 1k/10k correctness/capacity initial
gate 已通过；但 100k 未完成，整个 current-head capacity gate 仍未通过，release 仍为
`NOT_READY`。

100k 已完成的两个 arm 均通过 lost/duplicate/orphan/attempt mismatch = 0：

- `fair-q100000-single_tenant-w1-b1`：100 jobs，202.142s，0.495 Jobs/s，claim p50/p95/p99
  1148/2959/3055ms，result commit p95 48.7ms，lock-wait peak 0；
- `fair-q100000-single_tenant-w2-b1`：100 jobs，124.978s，0.800 Jobs/s，claim p50/p95/p99
  1510/4012/6260ms，result commit p95 192.8ms，lock-wait peak 1。

w4 未生成 runtime raw；Compose 中三个 `canceling statement due to user request` 出现在首个 worker
异常后，符合 `TaskGroup` 取消 sibling 的行为，不能反推它们是根因。原 `failure.json` 只保存
`error_type=ExceptionGroup`，没有叶异常、cause 或 traceback。这使“协议故障、租约丢失、数据库
错误或性能边界”无法区分；在根因未知时修改 production scheduler 不符合本阶段规则。

### RED、最小修改与 GREEN

先新增纯函数测试，构造 `ExceptionGroup(RuntimeError caused by TimeoutError)`，要求失败报告保存
顶层消息、叶异常、cause、固定时间和包含两层异常的 traceback。首次执行：pytest collection
因 `build_failure_report` 不存在而失败，形成有效 RED。

最小修改仅位于 evidence harness：`build_failure_report` 递归序列化 BaseExceptionGroup children、
cause/context，并保存 `traceback.format_exception` 的完整文本；CLI failure path 改为调用它。
不改变 fair selector、production claimer、lease、result commit、样本量或 resume-safe claim。
首次静态检查只发现新增 import 顺序的 Ruff `I001`，调整顺序后重新验证。

精确本地命令：

```powershell
$env:UV_CACHE_DIR='D:\文档\ai-evalops-platform\.codex-tools\uv-cache'
.\.codex-tools\Scripts\uv.exe run --no-sync pytest `
  tests/unit/scripts/test_fair_capacity_evidence.py -q
.\.codex-tools\Scripts\uv.exe run --no-sync ruff format --check `
  scripts/fair_capacity_evidence.py scripts/run_fair_capacity_test.py `
  tests/unit/scripts/test_fair_capacity_evidence.py
.\.codex-tools\Scripts\uv.exe run --no-sync ruff check `
  scripts/fair_capacity_evidence.py scripts/run_fair_capacity_test.py `
  tests/unit/scripts/test_fair_capacity_evidence.py
.\.codex-tools\Scripts\uv.exe run --no-sync mypy `
  scripts/fair_capacity_evidence.py scripts/run_fair_capacity_test.py
.\.codex-tools\Scripts\uv.exe run --no-sync pytest `
  tests/unit/scripts/test_release_candidate_workflow.py `
  tests/unit/scripts/test_release_evidence.py `
  tests/unit/scripts/test_fair_capacity_evidence.py -q
```

当前 GREEN：容量证据单测 `16 passed`；相关合同组合 `40 passed`；全仓非外部服务回归
`617 passed, 13 deselected in 373.08s`；315 files formatted；Ruff passed；MyPy 133 source
files passed；diff check passed。
下一次 remote run 的目标首先是获得可诊断的原始叶异常；只有 100k 全 16 arms VERIFIED 才进入
current-source 旧 32-arm load protocol。若同类根因复现，再根据叶异常与原始 PostgreSQL 诊断决定
是否需要最小生产修改。

## 2026-08-08 — 修正 EXPLAIN candidate cardinality 并加入 fail-closed 准入

### 修改前判断与真实证据

分析 `rc-gh-31262849253-1` 的 100k raw plan 时，原始 WindowAgg 明确包含
`Actual Rows: 100000.0`，但保存的 summary 是 `candidate_cardinality: 1`。原因不是 PostgreSQL
计划异常，而是 psycopg 将真实 JSON 数字解码成 float，`summarize_explain` 却只接受
`type(Actual Rows) is int`；现有单测使用整数，未覆盖真实驱动形状。

更严重的是旧 admission 只验证 EXPLAIN 格式、hash 和 exact coverage，不验证候选基数语义，
因此这类错误仍可能被判 `VERIFIED`。正在运行的 source `87cf01c...` 仍包含该缺陷，所以无论
其运行结论如何，只能保留为过渡/负面证据，不能作为最终 release capacity bundle。

### RED、最小修改与 GREEN

第一组 RED 把既有计划单测的 `Actual Rows` 改为真实的 `1.0/1000.0/10000.0`；结果只有
candidate 字段失败，期望 10000、实际 1。最小修复把非 bool 的 PostgreSQL int/float 行数统一
正规化为 int，并取整个 plan tree 的有效候选节点行数。直接对不可变 100k raw plan 复算得到：

```text
stored_candidate_cardinality=1
recalculated_candidate_cardinality=100000
```

补充的 legacy（无 WindowAgg）RED 首先得到期望 1000、实际 1；算法随后统一取整个 plan tree 的
最大 Actual Rows。真实 100k fair 与 legacy raw plan 最终均复算为 100000。

第二组 RED 构造 manifest/hash 完全自洽、queue_size=1000 但 candidate=1 的 bundle；旧 admission
错误返回 `VERIFIED`。最小合同修改要求 `arms.csv` 存在正 `queue_size`，且每份 fair/legacy
EXPLAIN 的数值 candidate 与所属 arm queue size 完全相等，否则 blocker 为
`postgres_explain_candidate_cardinality_mismatch`。正向测试夹具同步补齐真实字段；没有放宽其他
blocker。

最终相关验证：42 tests passed；4 files formatted；Ruff passed；MyPy 两个 evidence source
passed。使用新 admission 直接重验旧 initial 32-arm bundle，得到：

```json
{"status":"FAILED","arm_count":32,"blockers":["postgres_explain_candidate_cardinality_mismatch"]}
```

该修改只影响 evidence summary/admission，不改生产 claim、锁序、lease 或 resume-safe 行为。旧
manifest 和 raw evidence 保持原样，没有回写错误数字。

## 2026-08-08 — 100k/w8 lease loss：让租约从慢 claim 完成后开始

### 可诊断重跑与真实 RED

诊断提交 `dc178739bdc4aeac5a110f11cc405d4e4e355f8c` 的标准 CI run
`31263918298` success；专用 trigger source `87cf01c06102b6e4fa267ce5f7c96b29756f0fe6`
的标准 CI run `31263972501` 也 success（3m15s）。RC run `31263972530` 在 20m32s failure，
artifact `rc-gh-31263972530-1` 为 819 KB，digest
`sha256:05feb45a59bd3a820f76393c23bdc769c5aed9c01a5c892767cdb77ab28fc1c0`，immutable
evidence commit 为 `2036ace`。

新的 `failure.json` 成功穿透 ExceptionGroup：唯一 leaf 是
`LeaseLostError: result rejected because the worker no longer owns a live lease`，traceback 精确位于
`EvaluationWorker._process_claim → SQLAlchemyResultCommitter.commit_success`。100k single-tenant
w1/w2/w4 已各自 VERIFIED，correctness 的 lost/duplicate/orphan/attempt mismatch 均为 0：

- w1：120.149s，0.832 Jobs/s，claim p95 3008.7ms，commit p95 62.2ms，lock-wait peak 0；
- w2：195.037s，0.513 Jobs/s，claim p95 4202.7ms，commit p95 285.5ms，lock-wait peak 1；
- w4：209.035s，0.478 Jobs/s，claim p95 11905.7ms，commit p95 635.1ms，lock-wait peak 2；
- w8 未生成 runtime raw，在 worker sample 中 lease loss 后 TaskGroup 正确取消 sibling。

### 根因判断

harness 与生产默认均为 lease 30s、heartbeat 10s、claim batch 1。源码确认
`SQLAlchemyJobClaimer.claim` 在执行昂贵 fair candidate SQL **之前**计算 `now` 和
`lease_expires_at=now+30s`，并在 contention retries 中复用。100k/w4 的 claim p95 已消耗 11.9s；
w8 的排序、锁等待和竞争可在 claim 返回前消耗完整租约。mock target 很快结束，不会到达 heartbeat
runner 的第一个 10s tick，result commit 因此携带已过期 lease 被 fencing 正确拒绝。

此证据支持修正“租约计时起点”，不支持放宽 stale completion、增加默认 lease 或重写 fair
scheduler。candidate SQL/外部排序仍是最严重性能瓶颈，但先修 correctness gate，再讨论优化。

### TDD、最小生产修改与效果

新增 `AdvancingClock` RED：模拟候选查询耗时 20s。旧实现返回的 lease 在查询开始后 30s 到期，
只剩 10s；断言要求查询完成后仍有完整 30s，测试按预期失败。最小修改为：

1. 每次 contention attempt 读取新的 `eligible_at`，仅用于候选资格；
2. 候选 SQL 返回并锁定 rows 后读取一个 `claimed_at`；
3. lease expiry、job heartbeat/started、attempt started、tenant fairness timestamp 与 progress event
   全部基于同一个 `claimed_at`；
4. 固定 lease 长度、heartbeat 间隔、fair SQL、Tenant→Run→Job 锁序与 version fencing 均不变。

额外把 contention-retry 测试改为四阶段推进时钟，证明第二次 attempt 也使用新资格时刻与新
claimed_at。claiming unit 7 passed，包含 worker/result/lease runner 的相关组合 17 passed，扩大到
harness/合同为 37 passed。

首次把 MyPy 扩到 `tests/unit/jobs/test_claiming.py` 时出现两处既有 `object.compile` 类型错误；项目
正式 MyPy 范围不含 unit tests，没有为消除输出而改写既有 helper。正式命令随后发现
`InstrumentedClaimer._claim_once` 仍覆盖旧签名；同步为 `eligible_at` 后，MyPy 133 source files
passed，Ruff/format/diff check passed。最终全仓非外部服务回归为
`620 passed, 13 deselected in 351.58s`。

该修改改变 production claim 的时间戳起点，但不改变 resume-safe claim 语义：仍在同一 transaction
内锁定 Job/Tenant、写 attempt、设置 owner/version/lease；stale success/failure 仍按 owner、version
和 live lease fail-closed。下一步必须用真实 PostgreSQL 重跑 1k/10k/100k，证明 w8 不再 lease loss；
在此之前 release 仍为 `NOT_READY`。

## 2026-08-09 — RC 重跑暴露 Bitmap Index 死元组计数误判

### 运行结果与保留证据

租约计时修复后的精确 source `aac76ed05dd17092f39ead7821ceb50abd205770` 触发标准 CI run
`31265533926` 与 RC capacity run `31265533928`。标准 CI 在 3m54s 后成功；RC 在 6m30s 后失败，
但 always-preserve 路径正常上传 artifact `rc-gh-31265533928-1`（742 KB，digest
`sha256:b0a45c0892a464346091cb3f179368edb408789e19b65d294965ad8bb39ebd10`），并由机器人提交
`d1c0272` 原样保存 297 个证据文件。该失败没有被删除、覆盖或改写成成功。

`initial/assessment.json` 证明 32 个 1k/10k arms 全部执行完成：expected/observed 均为 32，
missing/duplicate/unexpected 均为空，source 与 expected source 均精确为 `aac76ed...`；唯一 blocker 为
`postgres_explain_candidate_cardinality_mismatch`。因此这不是 worker correctness、租约或 arm
coverage 失败，也不能被当作 VERIFIED，更不能进入 100k stage。

### 从表面“队列累积”到真实 PostgreSQL 语义

逐份检查 256 个 EXPLAIN summary 后，24 份不匹配全部集中在 q1k/single-tenant：w2、w4、w8 的
fair 与 legacy FIFO 各 4 次 repetition，candidate 分别为 2000、3000、4000。这个等差模式最初看似
fixture 未清理；但原始计划显示父 `Bitmap Heap Scan on evaluation_jobs` 的 `Actual Rows` 始终为
1000，只有子 `Bitmap Index Scan` 上升为 2000/3000/4000。PostgreSQL bitmap index 阶段可以返回
尚未 vacuum 的死索引 TID；heap scan 执行 MVCC 可见性检查后才得到真实可见队列。此前“取整棵计划
树最大的 Actual Rows”把物理索引 TID 数误当成业务候选作业数，门禁本身严格正确，错误位于摘要
字段的语义。

### RED、最小证据工具修复与效果

先加入包含 4000 个 Bitmap Index TID、但只有 1000 个可见 heap rows 的回归测试。旧实现按预期
失败：`assert 4000 == 1000`。最小修复只修改 evidence summarizer：

1. fair 计划存在 `WindowAgg` 时，优先取该语义边界的可见候选行数；
2. benchmark-only legacy FIFO 无 `WindowAgg` 时，取 `evaluation_jobs` 表访问节点的最大可见行数；
3. 只有缺少上述语义节点时才回退到其他 plan nodes，并明确排除 `Bitmap Index Scan`；
4. 不修改 production fair SQL、锁序、lease、heartbeat、fencing、样本量或 admission 等值要求。

修复后 evidence/release 相关测试为 `40 passed`；提交前最终验证为：2 个改动 Python 文件格式正确、
Ruff passed、MyPy 3 个 evidence source passed、diff check passed，完整非外部服务回归
`621 passed, 13 deselected in 363.19s`。随后直接对本次真实 artifact 中 256 份 raw
EXPLAIN 离线重算，结果为 `mismatches=0`：q1k fair 64/64、q1k legacy 64/64 均为 1000，q10k
fair 64/64、q10k legacy 64/64 均为 10000。这个离线结果只验证修复算法能正确解释已保留 raw
计划；原 bundle 的 immutable summary/manifest 仍保持 FAILED，不回填为成功。必须提交新 source
并重新运行 source-bound 1k/10k/100k workflow，才可建立最终 release capacity 证据；此刻 release
继续为 `NOT_READY`。

## 2026-08-09 — current fair 1k/10k/100k 容量门完整通过

### 精确运行身份与不可变产物

修复提交 `4996fe0` 与独立触发提交 `f8b96fd` 推送后，精确 source
`f8b96fdd8a4e88f0bd1b162b95daa166f2a49aef` 触发：

- 标准 CI run `31266366601`：success；quality-and-integration 3m09s，Compose smoke 1m17s；
- RC capacity run `31266366590`：success；fair-capacity job 1h10m；
- artifact：`rc-gh-31266366590-1`，1.08 MB，
  `sha256:1f4eb2e7ca1e49a43376e98a4e8c6d2e37fcb7cc1e0c163b8c70ac19a8c680ab`；
- immutable evidence commit：`0c315cb`。

采证期间本地没有推送或编辑证据目录；工作流结束后才 fetch 并 fast-forward。initial 与 large
assessment 均为 `VERIFIED`，source/expected source 精确相等，blockers 为空：initial 32/32 arms，
large 16/16 arms，均无 missing/duplicate/unexpected。

### 独立重验及核验脚本中的两次假设错误

没有只接受生成器自己的绿色状态，而是重新调用 release admission、重算 manifest 文件集/大小/
SHA-256，并遍历全部 raw 与 EXPLAIN。第一次独立脚本错误地把 `lost_count` 当作 raw 顶层字段，实际
schema 将一部分 correctness 字段放在 `correctness` 对象中；脚本因此 `KeyError`，没有说明证据
失败。第二次错误地要求每份 EXPLAIN 重复包含 `source_commit`；真实合同由 stage manifest 与
assessment 绑定 exact source，单份 EXPLAIN 不重复该字段，因而出现 384 个假阳性。两次都只修正
临时只读核验逻辑，没有修改产物或生产代码。

按真实 schema 的最终独立结果为零错误：

| Stage | Arms | Raw | EXPLAIN | Manifest payload files | Submitted/terminal | Runtime/EXPLAIN errors |
|---|---:|---:|---:|---:|---:|---:|
| initial（1k/10k） | 32 | 32 | 256 | 290 | 3200/3200 | 0/0 |
| large（100k） | 16 | 16 | 128 | 146 | 1600/1600 | 0/0 |
| 合计 | 48 | 48 | 384 | 436 | 4800/4800 | 0/0 |

所有 raw arm 的 lost、duplicate durable result、orphan、attempt mismatch、stale success/failure
accepted 和 illegal transition 均为 0。384/384 EXPLAIN 的 candidate cardinality 与所属 queue size
精确相等。20:1 分布中 fair 次租户最晚位置为 2；legacy FIFO 最早位置在 initial 为 953、在
100k 为 95239，证明公平语义在三个队列规模均保持，而不是借用旧 source 的 correctness。

### fixed-sample 性能、资源与瓶颈

以下 Jobs/s 是“每臂在既定 backlog 中完成 100 个真实 worker 样本”，不是完整排空队列吞吐：

| Queue | Jobs/s min / median / max | Claim p95 ms min / median / max | Fair plan median ms min / median / max | Legacy plan median ms min / median / max |
|---:|---:|---:|---:|---:|
| 1k | 3.066 / 32.164 / 54.012 | 18.478 / 144.108 / 2360.747 | 6.027 / 9.531 / 481.971 | 2.003 / 3.224 / 3.556 |
| 10k | 4.452 / 7.433 / 13.245 | 69.096 / 440.842 / 3788.800 | 52.575 / 79.773 / 106.474 | 27.663 / 34.549 / 47.941 |
| 100k | 0.282 / 0.462 / 0.921 | 2523.467 / 8541.875 / 48522.589 | 726.741 / 1218.029 / 2281.322 | 311.178 / 357.042 / 508.342 |

100k 最慢 arm 是 many-small/w8：354.346s、0.282 Jobs/s；最快是 skew/w1：108.536s、
0.921 Jobs/s。历史失败点 single-tenant/w8 本次完整 VERIFIED：298.133s、0.335 Jobs/s、claim p95
48522.589ms、commit p95 1117.129ms、100/100 terminal、correctness 全零，证明 post-selection lease
起点消除了该场景的假性过期，但没有消除昂贵 claim。

100k fair/legacy paired plan latency 比值的 arm 中位数为 3.087，范围 2.213–6.156；最大值位于
skew/w1（2039.292ms 对 331.271ms）。100k 最大 RSS 106,921,984 bytes、最大 PostgreSQL
connections 12、最大 waiting-lock connections 2。证据因此支持的瓶颈判断是：fair 的全候选排序/
窗口查询及其并发放大是主要容量成本，result commit 次之；但 correctness、source-bound gate 和
240 分钟工作流均已通过，本 RC 阶段没有测得要求再次修改 production scheduler 的功能性回归。

此时 1k/10k/100k current fair capacity gate 已完成，但 release 仍暂为 `NOT_READY`：尚需对同一
current source 执行历史兼容的正式 500-case/32-arm worker-scaling 协议，并完成最终 release 文档与
一致性审计。

## 2026-08-09 — 准备 current-source 500-case/32-arm 同协议重跑

容量 gate VERIFIED 后才检查 `.github/workflows/evidence-gate.yml`，没有提前并行启动另一个正式实验。
现有 workflow 精确固定 workers `1,2,4,8`、cases `500`、warmup `50`、repetitions `4`、seed
`1729`，由 load harness 的两个 workload 组成 2 × 4 × 4 = 32 arms；prepare 与 execute 使用同一
参数，source 绑定 `GITHUB_SHA`，产物写入新的不可变 `gate1-gh-<run>-<attempt>` 目录。因此它与
pre-fair source `15e7ac2...` 的正式协议相同，适合 current RC 的直接对照，不需要改 workflow 或
生产 scheduler。

首次把 CLI help、`test_experiment_scripts.py -k load` 和 diff check 合在 120 秒工具时限中执行，
命令在 124 秒被终止且没有 pytest 结果；这不是 GREEN，也没有失败断言。拆分后 CLI help 在 3.5 秒
正常退出，load 协议测试获得明确结果：`9 passed, 6 deselected in 225.45s`。随后才把
`.github/evidence-gate-trigger.txt` 的请求时间更新为 `2026-08-09T01:27:53+08:00`。该 trigger
提交的目的仅是运行冻结 32-arm 协议；在机器人完成不可变 evidence commit 前，不推送后续文档。

## 2026-08-09 — 32-arm 执行成功但 evidence 回写被超大日志阻断

精确 source `09c3e7d2f70daf5629b2f876eaaefddedb20d6c5` 的标准 CI run
`31269813704` 成功；worker-scaling run `31269813705` 在 29m30s 后显示 failure。不能仅凭工作流
总状态把它记成实验失败：GitHub jobs API 的逐步结论表明，checkout、依赖、prepare、Compose、迁移、
服务启动、API readiness、临时密钥、冻结 32-arm execute、诊断和 artifact upload 全部 success，唯一
失败步骤是 `Commit immutable evidence to the target branch`。

artifact `gate1-gh-31269813705-1`（artifact id `9025594324`、下载大小 17,490,693 bytes、
digest `sha256:af5d76fab30b2beba9c0b080fa931b8065b9a3f46b23b8dcadcab99061f60560`）因此通过
GitHub Actions API 恢复到本地。恢复时没有打印 credential 值；临时 credential request 文件随后
删除。包内 `execution.json` 为 `completed`，32/32 arms 均标记
`valid_for_capacity_comparison: true`，`failures/index.json` 为空；final aggregate 的 quality gate 为
`VERIFIED`、32/32 complete、没有 missing/invalid/blocker。adoption gate 为 `NOT_RUN` 且 review
readiness 为 `READY_FOR_HUMAN_REVIEW`，这是冻结协议要求人类决定 worker 数的设计，不是 execute
失败；API 的 step 13 success 也独立印证了这一点。

检查未回写目录的文件大小后找到直接原因：`environment/compose.log` 为 122,939,753 bytes，超过
GitHub 单文件 100 MiB 上限；其余最大文件约 0.5 MiB。由此判断应修 evidence diagnostics 的无界
日志保存，而不是改 production scheduler、32-arm 结果或准入结论。

按 RED→GREEN 增加三条工作流合同测试，覆盖 worker scaling、fault matrix 和 RC fair capacity。
第一次 RED 中，worker scaling 与 RC 正确因缺少上限失败，但 fault 测试先因测试夹具误写 job 名
`fault-evidence` 而 `KeyError`；将真实 job 名纠正为 `fault-matrix` 后重新执行，三项均只因没有
`COMPOSE_LOG_LIMIT_BYTES=10485760` 失败。随后对三条持久化证据工作流采用相同最小修复：

1. Compose 完整日志只暂存在 runner 临时目录，不直接进入 Git；
2. evidence 仅保留最后 10 MiB，以保留最接近终止点的诊断；
3. `compose-log-policy.txt` 明确记录策略、字节上限、原始/保留大小和 compose logs 退出码；
4. 生成受限副本后删除 runner 临时文件，不改变实验 raw/final/manifest 或生产代码。

GREEN 结果为新合同与既有 RC workflow 合同合计 `6 passed in 0.10s`，YAML 可正常解析，
`git diff --check` 通过。当前下载 artifact 的超大原始日志仍须先记录原始 SHA-256，再生成受限可提交
副本；完成清单复核前不把恢复目录称为已提交的 immutable bundle。

提交前第一次组合验证不能采用：Ruff format 报告新测试需统一两处字符串引号，且命令引用了不存在的
`tests/unit/scripts/test_experiment_workflow.py`，pytest 因路径错误显示 `no tests ran`；末尾的
`git status` 又把 PowerShell 整体退出码覆盖成 0。没有据此宣称通过。使用真实文件列表纠正命令、
让每一步在非零时立即退出，并用 Ruff 机械格式化后，最终结果为 Ruff check 通过、format check
通过、两份真实 workflow 测试 `6 passed in 0.09s`、diff check 通过。

## 2026-08-09 — 恢复包独立核验、Git-safe 保存与 pre-fair 配对比较

在裁剪任何文件前，项目自己的 `validate_gate1_final_bundle` 对恢复包重新读取并核验：final status
`complete`、32 arms、664 payload files，文件集、大小、SHA-256、summary/raw/plot 交叉引用全部通过。
全目录符号链接计数为 0，常见 GitHub token、Bearer authorization 和明文 password 模式命中为 0。

原始 `environment/compose.log` 的固定身份是 122,939,753 bytes、SHA-256
`5bed872f1ba845314f75582df55ba1aeaaf774eb64a81428d9235a1a2a270ccb`。原始完整包仍可由
artifact id `9025594324` 和 artifact digest 取回（GitHub retention 90 天）。本地可提交副本只把该日志
替换为最后 10,485,760 bytes，保留日志 SHA-256 为
`442e658ac5c543048e1f20ddaa163bf41c0b61fb10c2c2c29433219e964997a4`；原始/保留身份、原因、
source 和 artifact 身份均写入 `environment/compose-log-policy.txt`。裁剪后整个恢复目录为
86,587,166 bytes；`final/` 下的 664 个受 manifest 约束文件没有修改。

current run 与 historical pre-fair run 使用相同的 2 workloads × 4 worker counts × 4 repetitions、
500 measurement cases、50 warmup、seed 1729。按 workload/worker 分组后的吞吐中位数对照如下：

| Workload | Workers | Pre-fair Jobs/s | Current fair Jobs/s | Change |
|---|---:|---:|---:|---:|
| io latency | 1 | 21.481 | 15.470 | -27.98% |
| io latency | 2 | 38.062 | 30.761 | -19.18% |
| io latency | 4 | 56.263 | 27.198 | -51.66% |
| io latency | 8 | 66.804 | 10.985 | -83.56% |
| transient 5% | 1 | 19.587 | 18.823 | -3.90% |
| transient 5% | 2 | 34.031 | 28.511 | -16.22% |
| transient 5% | 4 | 50.825 | 17.080 | -66.39% |
| transient 5% | 8 | 60.759 | 12.642 | -79.19% |

32 个同名 arm 的配对变化中位数为：吞吐 `-48.30%`、end-to-end `+93.50%`、queue-wait p95
`+104.22%`、claim mean `+464.19%`、result transaction mean `+30.49%`、worker RSS peak
`+4.73%`、worker CPU peak `+1.89%`。吞吐变化范围为 `-93.97%` 至 `-2.54%`，没有任何 arm
优于历史吞吐；current aggregate 还明确记录两个 workload 的 2→4 和 4→8 负扩展。因资源增长很小而
claim 时间显著增长，数据与 100k EXPLAIN/claim 结论一致，瓶颈优先指向公平候选查询和并发锁竞争，
而不是 worker CPU/RSS 饱和。

但两次 GitHub runner 并非同一 CPU：pre-fair 为 4-vCPU AMD EPYC 7763，current 为 4-vCPU
Intel Xeon Platinum 8370C；内存约 16.76 GB、Docker 28.0.4 和 Compose 配置一致。故这些结果足以
证明 current source 存在显著容量/负扩展风险，却不足以把全部百分比严格因果归于 scheduler，亦不能
建立跨硬件性能 SLO。release 文档必须同时披露回归、环境差异和“2 workers 是本次 current runner
的最佳中位吞吐点”；不得继续把 pre-fair 8-worker 3.11× 当作 current fair 性能。

第一次 evidence 提交尝试在 `git add` 后被 `git diff --cached --check` 阻断，未产生 commit。原因是
恢复的 `compose-ps.txt` 和 Compose/OTel 原始诊断日志天然包含大量行尾空格，而不是手写代码或文档
引入格式错误。清理这些空格会改变已记录的 retained SHA-256，降低证据可追溯性，因此不改写原始
诊断；后续只对手写 `EXECUTION_LOG.md` 执行 whitespace check，并允许生成证据保留原字节。

## 2026-08-09 — 性能门触发：按 tenant rank 做等价候选剪枝

重新核对 RC 指令后不能直接写 READY：相同协议的 8 个 workload/worker 组中有 7 个吞吐中位数回退
超过 15%，触发 release performance investigation threshold。此时停止发布文档定案，按指定顺序先查
ranked CTE candidate cardinality，不添加新队列系统或调整正确性语义。

current 100k/single-tenant/w1 的真实 PostgreSQL fair EXPLAIN 显示：candidate cardinality 100,000；
WindowAgg 输出 100,000，后续三个 Hash Join 和外层 Sort 都处理 100,000 行，最终 Limit 只返回 1；
execution 799.618ms，外层 Sort 为 external merge，temp read/write 15,467/27,259 blocks。证据直接支持
“没有按 claim batch 剪掉不可能入选的 tenant ranks”这一单一假设。

等价性依据：对 batch limit N，任一 tenant rank 大于 N 的 job 之前已经有同租户 N 个 priority 不低、
rank 更小的 job；在全局 `priority DESC, tenant_rank ASC, tenant_last_claimed_at, created_at, id`
顺序下，它不可能进入前 N。因此可在外层 join/lock/order 之前增加
`tenant_candidate_rank <= limit`，同时保留 WindowAgg、公平排序、Tenant/Job `FOR UPDATE SKIP LOCKED`、
eligibility recheck、contention retry、lease/fencing 和 batch 1–100 合同。

RED 新增 SQL 合同断言，要求 limit=10 时编译 SQL 包含
`ranked_claim_candidates.tenant_candidate_rank <= 10`；旧实现按预期 `1 failed, 7 deselected`。第一次
补丁错误命中 CTE 内部第一个 `.where`，形成定义前自引用；在运行 GREEN 前立即重读源码发现并移动到
外层查询，没有提交该错误。最终最小 production change 只有一个外层 predicate；GREEN 为 claiming
unit `8 passed`、Ruff passed、2 files formatted、MyPy 1 source passed、手写差异 whitespace check
passed。

该修改不改变 resume-safe claim：状态转换、attempt/version、lease owner/expiry、heartbeat、Tenant 与
Job 锁、stale result fencing 均不变。它目前只由 SQL 合同和数学等价性支持，尚未得到真实 PostgreSQL
性能/正确性回归结果；必须推送后重新运行标准 CI、10W/100J/20:1/fencing，以及 current source 的
large queue 和 32-arm 协议，才能决定 release。

## 2026-08-09 — 第一次 rank 剪枝 remote failure 与 CTE 物化修正

提交 `e04491d` 推送后，同一 exact source 启动 CI `31271973224`、worker scaling
`31271973235`、RC capacity `31271973239` 和 fault matrix `31271973253`。CI 的
quality/integration 与 Compose smoke 均 success，证明现有 10W/100J、20:1、公平/锁序/fencing
合同未回归。RC 在 initial stage failure，100k 按 fail-closed 协议 skipped；artifact
`rc-gh-31271973239-1`（id `9025917351`、digest
`sha256:9f58c16366cb134b0f02d5ec792d893f6fd55e17631a613a2cd92c91d7db7b52`）上传，机器人提交
`54cadeb` 原样保存。assessment source/expected source 均为 `e04491d...`，32/32 arms 完成、无
missing/duplicate/unexpected，唯一 blocker 是 `postgres_explain_candidate_cardinality_mismatch`。

该 blocker 的直接原因是 rank predicate 被 PostgreSQL 下推为 WindowAgg `Run Condition`，使 evidence
summary 把输出 rank 数 1/4/100 误作完整队列基数。更重要的是 raw plan 证明非物化 CTE 被内联：
q1k/single/w1 的 WindowAgg `Actual Loops=1000`、fair EXPLAIN 107.581ms；balanced q10k 的
evaluation_jobs Seq Scan 10,000 rows × 4 loops。故第一次优化虽然 SQL 等价、correctness CI 通过，
却产生 planner 重复执行风险，不能视为性能 GREEN。

针对“内联导致窗口重复执行”新增第二条 SQL 形状 RED，要求
`ranked_claim_candidates AS MATERIALIZED`；旧 SQL 按预期失败。最小修正仅给现有 ranked CTE 添加
PostgreSQL `MATERIALIZED` 前缀，保留外层 `tenant_rank <= limit`、顺序、锁、eligibility 和 fencing。
GREEN 为 claiming `9 passed`、Ruff/format/MyPy 全过。该修正必须再次 remote 验证后才可评价效果。

四条工作流并发写同一分支还暴露基础设施风险：RC 先推进远端到 `54cadeb`，较慢的 worker-scaling 与
fault 机器人稍后可能因 non-fast-forward 无法回写；artifact upload 位于 push 之前，原始实验仍会保留。
这不改变实验结果，但最终工作流应共享回写串行化或采用独立 evidence 分支。

## 2026-08-09 — 修正 Run Condition 计划的 candidate cardinality 解释

FAILED bundle 不回写：其原 summary/manifest/assessment 保持 `FAILED`。修复只面向下一次 source-bound
生成和对已保存 raw EXPLAIN 的离线验证。

第一条 evidence RED 构造 WindowAgg `Actual Rows=1`、Run Condition rank<=1、可见
`evaluation_jobs` Bitmap Heap Scan 1,000 rows、Bitmap Index 4,000 TIDs；旧 summarizer 返回 1，
预期 1,000。最初把 heap relation 放到 WindowAgg 之前后该 RED 通过，但对真实 256 plans 仍有 56
mismatch：多租户按 run 重复 heap scan 时只读取了每循环平均行数。第二条 RED 要求 Bitmap Heap
`10 rows × 100 loops = 1,000`；加入 row visits 后 mismatch 降到 48，却把 balanced q10k 的重复
全表 Seq Scan `10,000 × 4` 错算成 40,000。这一中间算法没有提交，也没有放宽 gate。

第三条 RED 明确重复全表 Seq Scan 仍代表同一 10,000 行，不能乘 loops。最终语义为：

1. 无 Run Condition 的 WindowAgg：其输出行数是完整候选基数；
2. 有 Run Condition 的 WindowAgg：其输出是保留 rank 数，取直接输入节点行数且不乘相关子计划 loops；
3. benchmark-only legacy：Seq Scan 取每次可见全表行数；按 run 分区的 Bitmap Heap/Index heap
   取 rows × loops；
4. 始终排除 Bitmap Index Scan TID 数，避免再次把 MVCC 死元组算成可见作业。

最终 release/evidence 单测 `43 passed`，Ruff/format/MyPy 通过；使用新 summarizer 对失败包全部 256
份 raw fair/legacy EXPLAIN 离线重算，`mismatches=0`。这只证明 raw 计划可被正确解释，原 bundle
仍为 FAILED；下一次正式 workflow 必须从新 source 重新生成 summary、manifest 与 assessment。

最终修复 source `1eff237620c06b7121b922f7ef6373965f90bc32` 的标准 CI run
`31272570667` 完整 success；Compose smoke 与 quality/integration 均通过。为避免专用 workflow 再次
并发回写，下一轮按 RC capacity → worker scaling → fault matrix 串行触发。本次只更新
`.github/release-candidate-trigger.txt` 为 `2026-08-09T02:46:46+08:00`，目标是先验证 1k/10k，
只有 assessment VERIFIED 才由同一 workflow 进入 100k；在结果回来前不触发另外两条最终实验。

## 2026-08-09 — 恢复并发工作流未回写的优化中间证据

第一次 rank 剪枝 source `e04491d360ae32ae54f428e3ef067fa05f83ee3c` 同时触发了多条会向同一分支
回写证据的工作流。RC 工作流先提交 `54cadeb` 后，worker-scaling run `31271973235` 与 fault
run `31271973253` 的实验和 artifact upload 均已成功，但最后的 Git push 因 non-fast-forward 失败。
这属于证据持久化竞争，不是实验执行失败。为避免丢弃负面结果，分别从 GitHub artifact 恢复为：

- `docs/results/load/gate1-gh-31271973235-1/`：artifact id `9026335273`，下载大小
  9,825,907 bytes，digest
  `sha256:44e9fd3e4354749c0a5d684c54a574e2da19aafdb2076869ea666d56103023a0`；
- `docs/results/fault/fault-gh-31271973253-1/`：artifact id `9025931491`，下载大小
  149,656 bytes，digest
  `sha256:10a1947b78c125ae7ad0a66dbfb90d35a4b2cbf0f2201e585da362e6adeae98e`。

恢复后没有凭工作流步骤名称直接信任内容。项目验证器重读 worker bundle，确认 final status `complete`、
32 arms、664 个 manifest payload，文件集、大小、SHA-256、summary/raw/plot 交叉引用全部一致；fault
验证器确认 status `complete`、3 repetitions、9 scenarios × 3 = 27 records、6 个 manifest payload，
且 report 为 `verified`。两个目录的符号链接计数均为 0；Authorization、Bearer、GitHub token 与明文
password 模式扫描命中 0。

这份 worker 证据必须作为负面中间结果保留：其 io-latency worker 1/2/4/8 吞吐中位数依次为
16.090、29.887、25.409、7.772 Jobs/s，transient-5% 依次为 17.194、24.691、19.057、
12.934 Jobs/s；两个 workload 均出现 2→4 和 4→8 负扩展。它证明仅添加
`tenant_candidate_rank <= limit` 并未解决 planner 内联放大，支持随后单独引入 CTE `MATERIALIZED`
的决定。fault 包证明该中间 source 的 27 个故障场景没有 correctness 回归，但不能替代物化后 source
的最终 fault 回归。

## 2026-08-09 — 物化公平候选的 RC 容量配对结果

最终容量 run `31272789199` 对 exact source
`9987a28d707653a45fffa60a283461e2514e3103` 执行；机器人提交 `2f828c9` 已快进同步。本地没有
复用 workflow 写出的 assessment，而是用 `build_fair_capacity_plan` 从 stage queue sizes 独立生成
预期 arm，再调用 fail-closed admission verifier 重算。结果为 initial 32/32 与 large 16/16 均
`VERIFIED`，missing/duplicate/unexpected 均为空，4 次 fair/legacy EXPLAIN 覆盖完整，source 与 row
source 绑定一致，manifest 文件集、大小和 SHA-256 全部通过，候选基数与 1k/10k/100k 队列一致，
所有 submitted=unique=terminal，lost/duplicate/stale accepted/illegal transition/orphan/attempt mismatch
均为 0，20:1 skew 的 fair 首个 secondary tenant 位置均不大于 2。

本轮与首个完整 fair RC run `31266366590` 均运行在 4-vCPU AMD EPYC 9V74、同一 Compose 协议与
相同 32-arm initial 矩阵上。按 queue size/worker 对 4 种 distribution 取吞吐中位数，变化如下：

| Queue | Workers | 剪枝前 Jobs/s | 物化后 Jobs/s | Change |
|---:|---:|---:|---:|---:|
| 1,000 | 1 | 33.764 | 32.088 | -4.96% |
| 1,000 | 2 | 45.082 | 54.185 | +20.19% |
| 1,000 | 4 | 30.375 | 52.443 | +72.65% |
| 1,000 | 8 | 23.758 | 29.912 | +25.90% |
| 10,000 | 1 | 10.694 | 24.833 | +132.22% |
| 10,000 | 2 | 9.791 | 26.246 | +168.06% |
| 10,000 | 4 | 6.530 | 15.526 | +137.77% |
| 10,000 | 8 | 5.779 | 9.358 | +61.94% |

32 个同名 arm 的配对吞吐变化中位数为 `+65.25%`。其中
`q1000-many_small_tenants-w1` 单次 runtime 样本为 `-43.93%`，但协议规定的主要 worker gate 使用
同 queue/worker 下跨 distribution 的中位数；全部 8 组都未超过 -15%，不能把单次 noisy arm 隐藏，
也不能反过来用它否定完整中位数协议。最终是否越过相对旧 formal baseline 的发布门槛，仍由随后
串行重跑的标准 32-arm worker-scaling 协议决定。

100k large subset 的 16 个 arm 全部 `VERIFIED`。公平 EXPLAIN execution median 相对同 fixture、
同 snapshot legacy FIFO 的比值范围为 `0.247–0.770`，中位数 `0.491`，超过 `3×` 的 arm 为 0；
Jobs/s 中位数 3.377，范围 0.628–5.488。高并发单租户仍显示明显 contention：w8 claim p95
41,386.537 ms、504 retries，因此 release 文档必须把“大队列高并发热点租户延迟”列为限制；但查询
计划数据已经否定“公平 SQL 比 legacy FIFO 慢 3×”这一特定门槛，不能据此引入新的队列基础设施。

## 2026-08-09 — 串行触发物化后最终 32-arm worker 回归

中间恢复证据已作为 `4a2748b` 单独提交并推送，远端分支不存在待回写的其他专用实验。此时才把
`.github/evidence-gate-trigger.txt` 的请求时间更新为 `2026-08-09T03:27:15+08:00`。该次触发只运行
标准 2 workloads × 4 workers × 4 repetitions 的 worker-scaling 协议，目的是在相对旧 formal
baseline 的相同协议上判定 -15% release gate，同时复核 10W/100J 执行正确性、资源、DB 与 claim
指标。fault matrix 尚不触发，避免两个证据机器人再次争抢同一目标分支。

## 2026-08-09 — 最终 32-arm 完整但性能发布门失败

触发 source `6acf72c3aa73c9fdc1664fe4e847fc8b8e90efd7` 的标准 CI run `31274490725` 与其前一
恢复证据提交的 CI run `31274460712` 均为 `completed/success`。worker-scaling run
`31274490704` 也为 `completed/success`，运行时间 2026-08-08T19:27:56Z 至 19:47:18Z；artifact
`gate1-gh-31274490704-1` 的 id 为 `9026814020`、压缩大小 9,702,555 bytes、digest 为
`sha256:099c7dff5302c82c61efc69ff1ddb634225883c0dd657adf7f3a61756da01d93`，过期时间
2026-11-06T19:27:56Z。机器人提交 `1c35e5b` 已通过 fast-forward 同步。

独立复核再次从 frozen arm order 读取预期，再重读 32 份 summary 与 final manifest：status
`complete`、32/32 arms、664/664 payload，文件集、大小、SHA-256、raw/summary/plot 交叉引用全部
通过，符号链接 0、常见 credential 模式命中 0。execution 32 arms 均
`valid_for_capacity_comparison=true`，共 16,000 submitted/unique/terminal succeeded，correctness、
collector gap 与 blocker 均为 0。第一次核验命令错误地从 final manifest 顶层读取
`source_commit`，触发 `KeyError`；检查 schema 后确认 source 位于 prepared manifest 的
`provenance.source_commit`，修正字段后完整验证通过。没有修改 evidence。

相对 historical pre-fair formal baseline `15e7ac2e28b70430acd0bff88ee6cc78e5b86a86` 的同协议
吞吐中位数如下：

| Workload | Workers | Pre-fair Jobs/s | Current RC Jobs/s | Change |
|---|---:|---:|---:|---:|
| io latency | 1 | 21.481 | 21.477 | -0.02% |
| io latency | 2 | 38.062 | 30.991 | -18.58% |
| io latency | 4 | 56.263 | 39.650 | -29.53% |
| io latency | 8 | 66.804 | 24.427 | -63.44% |
| transient 5% | 1 | 19.587 | 20.664 | +5.50% |
| transient 5% | 2 | 34.031 | 31.725 | -6.77% |
| transient 5% | 4 | 50.825 | 34.267 | -32.58% |
| transient 5% | 8 | 60.759 | 22.617 | -62.78% |

8 个主要 worker 组中 5 个回退超过 15%；组变化中位数 `-24.05%`，最差 `-63.44%`；32 个
同名 repetition arm 的配对变化中位数 `-29.55%`，范围 `-80.41%` 至 `+10.84%`。current run
内部也出现 4→8 负扩展：io `-15.22%`、transient `-11.65%`。pre-fair runner 是 4-vCPU AMD
EPYC 7763，current 是 4-vCPU AMD EPYC 9V74；因此百分比不是跨硬件生产 SLO，但协议、Compose
形状、job 数与 arm 顺序相同，且两个 workload 的高并发回退和 current-run 内部负扩展方向一致。
按本次 release gate 必须定为 `NOT_READY`，唯一 blocker 是公平 claim 在 4/8 workers 的吞吐与
扩展性，不能发布或声称 linear scaling。

本轮已按指令完成一个有证据的优化闭环：rank cardinality 假设 → SQL-shape RED → rank 剪枝 →
发现内联放大 → MATERIALIZED RED/最小修正 → paired 1k/10k/100k 与最终 32-arm。它显著改善了当前
fair 实现自身，但未越过 formal baseline gate。指令限制只允许一个假设/最小 production change，
因此此处停止继续性能调优，保留失败结果，不引入 Kafka/Celery/Temporal/Redis queue，也不改
resume-safe claim、lease、heartbeat、fencing、锁序或 result commit 语义。

本地验证第一次误用 `mypy app scripts tests`，因不同无包目录下两个 `test_repository.py` 被视为
duplicate module 而停止；这不是代码错误。改为仓库 CI 的精确范围
`mypy app scripts tests/integration tests/concurrency` 后，133 source files 无问题；Ruff format
为 318 files、lint all passed；pytest 为 `629 passed, 13 skipped, 3 warnings in 304.55s`。13 skips
是本机未启用真实 PostgreSQL/Redis/MinIO，3 warnings 是 Windows 临时目录清理 PermissionError；
配套 GitHub CI 已覆盖真实服务并成功。

## 2026-08-09 — 串行触发物化后最终 fault/fencing 回归

最终 worker evidence 已由机器人完整回写且本地复核结束，此时把
`.github/fault-evidence-trigger.txt` 更新为 `2026-08-09T03:49:56+08:00`。这次只运行 A–I × 3
fault matrix，用来确认物化公平候选后 stale success/failure fencing、lease reclaim、双 Reaper、
数据库/Redis 短断线、worker restart 与幂等提交没有 correctness regression。性能 gate 已失败，
但 correctness 仍必须独立闭合；该 fault 结果不会把 `NOT_READY` 自动改成 READY。
