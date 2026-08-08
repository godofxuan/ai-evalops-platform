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
