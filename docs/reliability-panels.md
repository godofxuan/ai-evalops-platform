# 多次运行可靠性报告：使用与边界

本功能为描述性扩展，不改变既有 DEMO/FORMAL 质量门槛。阶段与实际验证记录见 [执行记录](reviews/reliability-panels-execution.md)。

## 为什么不是再算一个平均分

相同平均成功率可能来自两种情况：部分题总是成功，或所有题偶尔成功。重复运行报告展示逐题成功次数、完整覆盖率、平均任务成功率、至少一次成功与全部成功比例。

每个 trial 是一个完整 durable paired experiment，内部仍有 baseline/candidate、各题 Job 和重试 Attempt。trial 不是 attempt。使用默认三次重试时，指标表示固定重试策略下的流程表现，不能称模型单次成功率。不同 UUID 也不证明采样独立、无缓存或无状态污染。

成功指标限定为 QA 的 reference_answer 或 Agent 的 agent_task_completion；权限、预算和工具错误单独披露。全部成功不代表综合质量 PASS。仅观测完整时给完整面板指标；执行失败、取消、未知和缺少报告分别保留，不通过删除题目提高分数。

## 执行前准备

需要已授权的 EvalOps API、真实 tenant ID、已上传的数据集版本，以及服务端注册的 baseline/candidate 目标。沿用 [持久客户端教程](durable-experiment-client.md)准备 request.json 与原始 product dataset.json。不要用归一化 JSONL 代替原始 product dataset。

另准备环境配置说明，记录超时、并发、模型及采样设置、缓存/状态重置策略、资源限制；对不含凭据的配置文档计算 SHA256。这里的环境摘要仅为客户端声明，平台不保证远端真的按此执行。目标实际组件摘要由服务端提交时冻结，面板只检查各 trial 间一致，并非预先配置认证。

服务执行代码 SHA 需与计划一致。它是实际部署的代码身份，不是自动拿当前本地 Git HEAD 当远端版本；不匹配会拒绝报告。该版本数据由现有服务配置及服务端快照提供，离线哈希不认证服务器真实性。

## 五步流程

安装仍用项目 Python 3.12 与原 uv.lock，不新增依赖。以下占位符必须换成你自己的已核对值；不复制示例凭据，也不要在命令行传 API key。

### 1. 先保存计划，再发起执行

```powershell
uv run --no-sync python -m scripts.product_reliability plan `
  --request path/to/request.json --dataset path/to/product-dataset.json `
  --tenant-id <真实租户UUID> --trials 3 `
  --evalops-sha <服务端完整40位代码SHA> `
  --environment-sha256 <无凭据环境配置的64位SHA256> `
  --sampling-kind TARGET_DECLARED --ledger artifacts/reliability-panel-01
```

plan 不访问网络，先验证题集摘要、资源预算与字段，原子创建私有 ledger。plan.json 保存独立 panel UUID、trial 总数、完整请求与身份；dataset.json 保留原始输入。每个 trial 的请求名和幂等键绑定完整计划摘要。已有目录拒绝覆盖。需要恢复时读原目录，禁止重建新计划来绕过失败；新的 plan 命令表示明确另开一组，应保留旧组。

SYNTHETIC 用于可控合成目标；TARGET_DECLARED 仅声明目标类型，不意味着真实模型独立采样已认证。客户端计划绑定标记为 CLIENT_PLAN_BOUND_ONLY，不是服务器可信时间戳或第三方预注册证明。

### 2. 提交固定 trial 集合

```powershell
uv run --no-sync python -m scripts.product_reliability `
  --api-url https://your-evalops.example --api-key-env EVALOPS_API_KEY `
  submit --ledger artifacts/reliability-panel-01
```

API key 由用户已有环境变量提供。每个 trial 提交独立 paired experiment，保存 receipt。若网络超时或客户端中断，重跑同命令、同 ledger、同键，由现有服务端幂等协议恢复，不再建一组结果。服务端执行不依赖客户端保持在线。

计划最多 10 次重复、每组不超过 20,000 个 case×trial 单元、总尝试预算不超过 200,000。总预算是已有限额的汇总上界，不是模型内部调用量或账单硬限额；增加重复次数会增加任务量与可能成本。

### 3. 收集结果（每次只检查一轮）

```powershell
uv run --no-sync python -m scripts.product_reliability `
  --api-url https://your-evalops.example --api-key-env EVALOPS_API_KEY `
  collect --ledger artifacts/reliability-panel-01
```

未结束 trial 保持未收集状态，不取消、不追加替代试验。已结束的成功、失败、取消实验都导出私有包，先按原始输入重算，核对执行/Run/计划身份后再原子保留。再次 collect 复用既有包；不重新调用目标。取消仍用原 product_experiment_client cancel 明确指定实验 UUID。

### 4. 离线生成私有报告

```powershell
uv run --no-sync python -m scripts.product_reliability report `
  --ledger artifacts/reliability-panel-01 --output-dir artifacts/reliability-report-01
```

输出 report.json 与可读 report.html，输出目录不能位于 ledger 内，不能覆盖。即使尚未收齐也可报告：MISSING_TRIAL 表示缺少该次已验证导出，不自动推断后台尚未提交或已经失败。需要区分当前执行状态请看 collect 输出。

报告只有在所有单元具有可用评分时才给 COMPLETE_DESCRIPTIVE_PANEL。缺失或错误时状态为 INSUFFICIENT_EVIDENCE，完整面板平均/any/all 为 null。observed_success_rate 单独展示已有观测比例，并与覆盖率并列，不能替代完整结果。

### 5. 从私有源证据重新验证

```powershell
uv run --no-sync python -m scripts.product_reliability verify `
  --ledger artifacts/reliability-panel-01 --output-dir artifacts/reliability-report-01
```

verify 从所有已收集的 durable 私有包与原始输入重新计算各试验，再重新汇总，比较 JSON 与 HTML，不是只检查自报 SHA。需同时保留 ledger 与对应报告目录；报告文件本身不能完成重算。如果报告后又 collect 到新 trial，旧不完整报告不会再匹配当前 ledger：应创建新输出目录保留新报告，不覆盖旧快照。

并发写入使用操作系统锁，进程退出后自动释放，无需删除常驻锁文件。进程硬杀可能留下 ledger 外的私有 `.reliability-stage-*` 临时目录；它们不阻塞恢复，但仍可能含数据。不要公开整个父目录；确认无在途进程和准确路径后，才由操作者处理遗留目录。本版本没有实现断电后 fsync 持久性保证。

## 读数时必须注意

- 经验 any/all 是当前固定 k 次面板的比例，不是无偏 pass@k 估计，不提供独立采样假设或置信区间。首次只做描述报告，没有修改成对 bootstrap。
- known_attempts、known_retries 仅统计有已验证导出的单元。未收集部分未知，不是零尝试。
- 成本仅累计 accepted observations；失败/被丢弃重试成本未完整采集，因此 total_execution_cost_usd 始终为 null。未知费用不补零。
- p95 使用已接受观测的 latency_ms 与 nearest-rank 规则，注明观测数量，不是队列等待、全部重试或端到端耗时。
- 组件漂移、租户/题集/代码/请求错配、跨 trial 复用 execution/run/job/attempt/result ID 都拒绝。公开投影不足以重算，不允许拿其汇总分数拼面板。
- JSON/HTML 不包含答案、prompt、工具参数，但 case ID 与关联摘要仍可能敏感；整个 ledger 和报告都按 PRIVATE 处理，不提交公开 GitHub。
- CLI 退出 0 表示该命令完成，不是质量通过；读取真实状态字段。正式 A/B、人评、生产资格与原性能限制保持不变。

## 可以怎样本地验证

无 API/数据库也可以运行单元回归：

```powershell
uv run --no-sync pytest tests/unit/product_experiments/test_reliability.py `
  tests/unit/product_experiments/test_reliability_client.py `
  tests/unit/scripts/test_product_reliability.py
```

这些使用明确标注的合成 durable 快照与 API 替代，只证明算法、恢复协议和文件边界。真实 worker/SQL/本地TCP路径位于既有 integration/test_product_experiment_persistence.py 调用的 product_reliability_support.py；必须有隔离迁移过的 PostgreSQL/Redis 才能运行。缺环境或 skip 不能当作通过。
