# 从异步评测后端到可使用的 RAG A/B 产品

## 1. 为什么要做这一层

项目原来并不是“没用”，而是能力集中在平台底层：租户、数据集版本、Run/Job/Attempt、Worker
租约、失败恢复、结果、轨迹、评审和证据门禁都已经存在。问题是新用户必须先理解很多内部概念，
才知道如何把两个 RAG 版本放进去比较。

这一轮新增的产品层把入口收敛为：

```text
Experiment Spec
  + frozen Dataset SHA
  + baseline provider + exact SHA
  + candidate provider + exact SHA
  + evaluator set + policy
             ↓
       paired execution
             ↓
case results / answer / citation / tool error / latency / cost
             ↓
paired bootstrap + sufficiency gate
             ↓
JSON evidence + HTML dashboard + human-review pending state
```

它没有替代原来的异步后端。这个轻量入口负责快速本地验证和对外演示；大规模、跨租户、可恢复的
执行仍应提交到现有 Run/Job/Worker 控制面。

## 2. 为什么是同题配对，而不是比较两个平均数

Baseline 和 Candidate 必须回答完全相同的问题。每道题先计算 Candidate − Baseline，再对配对差值
做 bootstrap。这样题目难度被配对关系控制，不会因为 Candidate 恰好拿到更容易的问题而获得虚假
优势。

当前正式策略冻结为：

- 至少 120 个共同 case；
- 六个类别各至少 20 个；
- case 集必须完全相同；
- 10,000 次 paired-percentile bootstrap，种子 `20260902`；
- task success 的 95% CI 下界不低于 0；
- citation correctness 的 95% CI 下界不低于 -0.02；
- tool error rate 的 95% CI 上界不高于 0.02；
- Candidate task success 和 citation correctness 的观测值均不得低于 0.80；
- Candidate tool error rate 的观测值不得高于 0.05；
- p95 latency 和 mean cost 的相对增加均不超过 25%。

相对差值和绝对下限必须同时满足，因此两个端点都完全失败时不能因为“0 对 0 无退化”而通过。
这仍不表示任意通过者都获得了业务价值认证。

## 3. 配置合同

`evalops.experiment/1.0` 使用严格 Pydantic 校验：未知字段直接拒绝，两个 arm 的顺序和角色固定，
source SHA 必须是 40 位小写 Git SHA，dataset SHA 必须是 64 位 SHA-256。

Provider 有两种：

- `fixture`：只用于确定性演示和回归；
- `http`：用于真实 HTTPS RAG/Agent endpoint，并复用已有的 DNS 解析、IP 校验、TLS/SNI 和
  peer-address 复核，防止配置变成 SSRF 通道。

HTTP 凭据只能写环境变量名称，例如 `CANDIDATE_RAG_TOKEN`。配置模型里没有 `api_key`、`token`
或 `password` 字段，因此明文密钥会作为未知字段被拒绝。

## 4. 一键演示

```powershell
./.venv/Scripts/python.exe -m scripts.build_product_demo_dataset --verify

./.venv/Scripts/python.exe -m scripts.run_product_experiment `
  --spec benchmarks/product_demo_v1/experiment.json `
  --output-dir artifacts/product-demo

Start-Process artifacts/product-demo/report.html
```

输出：

- `result.json`：唯一完整结果事实源；
- `baseline.json` / `candidate.json`：可交给正式质量工具复核的 arm 结果；
- `report.html`：无需服务器即可打开的 dashboard；
- `manifest.json`：每个文件的 SHA-256、byte size、执行命令和证据边界。

报告中的答案和 case 内容按不可信输入做 HTML escape，不能借由数据集注入脚本。

## 5. 接真实 RAG 时要做什么

1. 在运行之前选择 baseline 和 candidate 的精确 40 位 Git SHA，不得看到结果后换候选。
2. 两个 SHA 分别启动为 HTTPS endpoint；保证 endpoint 的响应映射含 answer、citations、trace、usage。
3. 冻结 120+ case 数据集并记录原始文件 SHA-256。
4. 把密钥放进两个不同的环境变量，仅在配置中写变量名。
5. 把 spec 的 `scope` 改为 `FORMAL` 并执行同一命令。
6. 自动结果通过后，使用单独保存的 blinding key 生成 A/B 隐藏的评审包。
7. 让两位真实、独立 reviewer 分别提交；未完成前保持 `HUMAN_REVIEW_PENDING`。

目前 RAG 当前 `main` 另有一份真实的 192 题 R5 公共聚合证据。它能被 EvalOps 做字节、
身份、成对计数、指标和声明边界验证，但公开文件刻意不含逐题问题/答案/结果，所以不能转成
这套 120-case 正式答案质量输入。运行：

```powershell
./.venv/Scripts/python.exe -m scripts.verify_external_aggregate_evidence `
  benchmarks/external_evidence/rag_r5_reference.json `
  <exact-rag-checkout>/docs/r5/evidence/uda_finance_r5_public_v1.json
```

验证成功的双状态是 `AGGREGATE_EVIDENCE_VERIFIED` + `FORMAL_CASE_RESULTS=INPUT_REQUIRED`。
具体来源、指标限定和仍缺的正式输入见 `docs/review/RAG_FORMAL_INPUT_AUDIT.md`。

## 6. 这次实现中遇到的问题与判断

### `uv` 不在 PATH

首次执行新测试时，Shell 返回命令不存在。处理方式是定位仓库已有 `.venv/Scripts/python.exe`，再用
`python -m pytest/ruff/mypy` 运行。这样没有安装或改变全局工具，也没有把环境错误记作测试失败。

### 严格模式中的 list/tuple

直接调用 `model_validate()` 时，strict 模式拒绝 Python list 自动转换为 tuple；从 JSON 读取时合同可以
正确解析数组。最终保留生产严格性，只让单元测试用正确的不可变 Python 输入，避免为了测试方便放松
配置边界。

### 为什么不直接接入 DeepEval/Ragas

本阶段核心指标可以确定性计算，硬依赖第三方评测框架会增加安装、模型调用和版本漂移。项目保留
Evaluator 协议和后续适配空间，但先证明自己最小闭环。这个取舍来自官方项目能力与许可证审计，
记录在 `OPEN_SOURCE_PRODUCT_BENCHMARK.md`。

### 为什么不修改 RAG

RAG 工作区存在另一任务的未提交文件，且跨仓库收口合同明确要求 EvalOps 只读消费。审计全部使用
远端 ref 的 `git show/grep/rev-parse`，没有 checkout、reset、worktree 或文件写入，避免污染用户工作。

### 为什么演示统计通过但正式 Gate 是 INPUT_BLOCKED

第一次完整演示暴露出一个语义冲突：顶层已经标记 `DEMO_PASS`，嵌套统计决策却仍继承
`formal_ab_eligible=true`。这会误导只读取 JSON 内层的审核者。修复后 demo 仍可展示统计 PASS，但
FormalEvidenceDecision 明确写入 `formal_ab_eligible=false`，其 decision outcome 为 `INPUT_BLOCKED`。

随后又主动检查了“双端都失败”的边界：只做非劣比较时，0 分 baseline 和 0 分 candidate 的差值是
0，可能错误通过。策略因此增加 Candidate 的绝对任务成功/引用正确下限与工具错误上限，并补了
equal-total-failure 回归测试。

## 7. 当前可说与不可说

可以说：实现了声明式、精确 SHA/数据集摘要绑定的 RAG/Agent 配对评测工作流，能自动生成质量、
引用、工具错误、延迟、成本的统计对比和可钻取报告；缺输入会 fail-closed。

不能说：真实 RAG 质量已经提升、正式双人盲审已完成、Shadow Gate 已通过、系统 production-ready。
