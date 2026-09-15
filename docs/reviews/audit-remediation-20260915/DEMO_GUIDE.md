# 三条可运行的演示路径

先阅读 CLOSEOUT_RESULTS.md。下面的目录都必须是新目录；不要覆盖原始报告。需要 Python 3.12 与仓库 uv.lock：

```powershell
uv python install 3.12
uv sync --locked --all-groups
uv lock --check
```

依赖准备可能联网；后面的离线 verify 不调用模型。真实私有答案、key、数据库转储不可提交或放进公开 ZIP。

## A. 不需要服务：本地固定演示

```powershell
uv run --no-sync python -m scripts.run_product_experiment --spec benchmarks/product_demo_v1/experiment.json --output-dir artifacts/qa-v3-demo --export-mode private
uv run --no-sync python -m scripts.run_product_experiment --spec benchmarks/agent_tool_demo_v1/experiment.json --output-dir artifacts/agent-v3-demo --export-mode private
uv run --no-sync python -m scripts.verify_product_experiment artifacts/qa-v3-demo/manifest.json
uv run --no-sync python -m scripts.evaluation_workflow analyze --bundle artifacts/qa-v3-demo --dataset benchmarks/product_demo_v1/cases.json --output-dir artifacts/qa-v3-analysis --include-private
uv run --no-sync python -m scripts.evaluation_workflow verify --bundle artifacts/qa-v3-analysis
```

打开 artifacts/qa-v3-demo/report.html，看首屏四问。verify_product_experiment 的结构校验不能替代下一条 analyze 里的完整重算；分析包会保存真实 verification scope。两个 120 题的 deterministic fixture 是教学样例，不是真实大模型效果或用户业务收益。

## B. 真实持久任务：固定 20×2 故障演练

先由操作者启动**新的可丢弃 PostgreSQL/Redis 开发实例**，填入自己的隔离 URL；不要指向共享生产库：

```powershell
$env:EVALOPS_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/ISOLATED_DATABASE'
$env:EVALOPS_REDIS_URL = 'redis://127.0.0.1:REDIS_PORT/0'
$env:EVALOPS_RUN_INTEGRATION = '1'
$env:EVALOPS_TEST_CODE_SHA = (git rev-parse HEAD)
$env:EVALOPS_AUDIT_EVIDENCE_DIR = (Join-Path (Get-Location) 'artifacts/my-matrix-new')
uv run --no-sync alembic upgrade head
uv run --no-sync pytest tests/integration/test_audit_fault_matrix.py -q -s --junitxml=artifacts/my-matrix-new.xml
uv run --no-sync python -m scripts.product_experiment_client verify artifacts/my-matrix-new/private
uv run --no-sync python -m scripts.product_experiment_client verify artifacts/my-matrix-new/public
```

实际注入、预算和顺序见 SYNTHETIC_PROTOCOL.md。断言40个计划项恰好出现一次：24 accepted、12 failed、4 cancelled、39 attempts、39 HTTP calls；私有 PRIVATE_RECOMPUTED，公共 PUBLIC_PROJECTION_ONLY。quality_status 必须 EXECUTION_FAILED。这是一个**预期的质量负结果，正确的平台验收结果**。同一任务恢复时产生的额外请求必须计数。

演练走真实应用鉴权/SDK、PG/Redis、worker、子进程强杀与本地 TCP。服务地址/DNS/peer 为测试夹具，不是公网 TLS 或生产 SSRF 验收。API 客户端在此演练用应用内 ASGI 通道；另有独立 SDK/CLI 回归覆盖客户端用法，不能将 ASGI fixture 说成公网 API 部署。

手动 submit/get/wait/cancel/export 的完整操作见 ../../durable-experiment-client.md，含数据集映射、目标注册与显式 Compose 覆盖配置。本轮本机缺 Docker/MinIO，未声称跑过该 Linux 部署流程。

## C. 不新增推理：公开四模型原件复核与发行门禁

公开实验的对象、历史数值及分母见 [四模型历史报告](../../../GEMMA_CROSS_FAMILY.md)。原包名 AI_EvalOps_Cross_Family_20260913.zip，SHA-256 为 3db9535f56a1ff9d3e0539664edb260aa542e3d7d98aeffd8eec8b316300e170。

在仓库根目录运行，output 选短且不存在的路径，避免 Windows 长路径：

```powershell
uv run --no-sync python -m scripts.replay_cross_family_delivery --archive PATH_TO_ORIGINAL_ZIP --output C:/Temp/eo-review-new
uv run --no-sync python -m scripts.prepare_bfcl_pilot --root artifacts/release-bfcl-new --download
uv run --no-sync python -m scripts.release_evidence_gate --root artifacts/release-bfcl-new --junit artifacts/release-bfcl-new.xml
```

第一条先核原 ZIP 与所有成员，使用其原 source snapshot 重算两 benchmark 的四模型比较。Python 审计钩子拒绝网络和子进程；不是系统级安全沙箱。第二条是下载固定上游判分材料，第三条运行真实 checker 控制，不调用模型。必需材料缺失或被篡改必须失败，不能 optional skip 变绿。原件14666个成员校验通过；本轮模型调用0，不能说新增了632次推理。

## 五分钟讲解

1. 先展示 README 三入口和“不保证什么”。
2. 打开 matrix 报告：任务失败与质量失败、缺观察/费用分别解释。
3. 对照 matrix-results.json：40计划项、39 attempts/calls，为什么不等于40或24。
4. 关闭目标服务后运行 private verify；再 public verify，解释验证层级差异。
5. 打开租约 red/green 日志及 CONTRACTS.md：锁前时间为什么失效，如何在数据库屏障中复现。
6. 讲一条 citation conflict 的执行失败，和一个 extra citation 的 recall/precision 差异。
