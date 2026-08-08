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
