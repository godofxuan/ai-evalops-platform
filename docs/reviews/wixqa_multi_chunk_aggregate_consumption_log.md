# WixQA Multi-Chunk 聚合证据接入记录

## 1. 修改前判断

本轮 RAG 证据描述的是同一固定 200 题 cohort 上的文章检索和重排结果。公开 artifact 没有逐题
问题、文章文本、case ID 或逐题输出，因此 EvalOps 只能验证聚合证据，不能生成 200 条正式
`CaseResult`。

开始修改前完成了以下精确核验：

- 发布者：RAG `main@ee6ee4e2eb534f4d36d2a6527b34b6b60dc0eeab`；
- 发布者 CI：`33630653251`，`completed/success`，head SHA 与发布者一致；
- 源证据：`d46a7766e362ec2bcb35afc7670113da9b18651e`；
- 源证据 CI：`33629262271`，`completed/success`；
- 引用 SHA-256：`67fb514c286c9618173a83e2309ac67d226097c2e7a5358c036a800afb2e01f7`；
- artifact SHA-256：`20305ad1a518b1cf6f86959b5ce1bcf0614a9678835f7794cd8bcf9faf1c7990`；
- protocol SHA-256：`777a28157848cc9f0f7311cb68f58116b2cac46ebb9be75cc5294ce99dd9f4db`。

发布者 CI 尚未完成时没有创建 pin。只有该精确提交的所有工作完成并成功后，才开始 EvalOps
修改。

## 2. 遇到的问题与设计选择

新 artifact 与旧 artifact 有两个结构差异：

1. 协议哈希位于 `protocol.sha256`；
2. `claim_boundary` 是包含 `allowed` 和 `forbidden` 的对象，而不是字符串列表。

没有采用任意深度递归搜索协议哈希，因为那可能错误接受无关嵌套字段。verifier 只显式接受已有
顶层形式和新的 `protocol.sha256`。

对于结构化声明边界，verifier 要求：

- 只能包含 `allowed` 与 `forbidden` 两个键；
- 两个列表都必须非空且全部为非空字符串；
- 两个列表必须分别与 producer reference 的 allowed/forbidden claims 按顺序精确一致。

这样 artifact 和引用不能分别呈现两套不同的允许声明。任何添加、删除、改写或顺序漂移都会
fail closed。

## 3. 结果边界

验证后的聚合事实包括：ExpertWritten 回顾性固定 cohort 上，候选 Recall/nDCG/MRR 为
`69.58% / 56.12% / 55.11%`，Dense 为 `66.42% / 52.16% / 49.61%`。MRR paired 95% CI
为 `[+0.74pp, +10.46pp]`，但 Recall 与 nDCG 的区间跨 0；p95 为 `693.73 ms`，多文章完整率
没有提升。

因此最终输出继续固定：

- `payload_granularity=aggregate_only`；
- `formal_case_result_status=INPUT_REQUIRED`；
- `formal_ab_status=NOT_RUN_BY_EVALOPS`；
- `formal_quality_claim_allowed=false`；
- `production_ready=false`。

可以说“在这个历史已消费的固定回顾性 cohort 上，MRR 配对区间高于 0”。不能外推为 fresh
blind 泛化、所有指标显著提升、答案准确率提升、生产延迟 SLO、默认生产配置或 EvalOps 正式
200-case A/B。

## 4. 回归测试

新增测试覆盖嵌套协议成功、结构化声明精确成功，以及声明漂移拒绝。已有错误发布者 SHA、私有
字段、错误协议和 aggregate-only 边界测试继续保留。tracked verification 中不含
`case_results`。

最终本地验证：`936 passed, 39 skipped`；Ruff lint、Ruff format、mypy 和最终证据 manifest
验证全部通过。39 个跳过项要求真实 PostgreSQL、Redis 或 MinIO 环境开关，没有被计为通过。
