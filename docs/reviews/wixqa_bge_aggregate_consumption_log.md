# WixQA BGE 聚合证据接入记录

## 1. 接入前判断

本轮输入来自 RAG 仓库的公开聚合导出，而不是逐题输入、逐题检索结果或 EvalOps 原生
`CaseResult`。因此可行的工作是验证来源、字节、协议、声明边界和聚合结论；不可行的工作是把
200 题数字扩写成 200 条正式结果，或声称 EvalOps 自己执行了正式 A/B。

接入前通过 GitHub API 和本地 checkout 同时核对：

- RAG `main`：`5b7a7518b63993d1f21aed441966db5032435d4a`；
- 发布者 CI：`33614494203`，`completed/success`，head SHA 与 `main` 完全一致；
- 源证据 CI：`33613059251`，`completed/success`，head SHA 为
  `3b717f7731ba270cad66ad748550b4372d3da746`；
- 导出 SHA-256：`540f30d52ddf0ded9e76cb573bfde1826aa0abbff86c9c0553a7284b83311e90`；
- 公开 artifact SHA-256：
  `9ad53224685254303cd4af808dd762e5ad15e662717893987998ae923b1376c6`。

## 2. 遇到的问题与修改理由

现有 verifier 只识别 artifact 顶层的通用字段 `protocol_sha256`。新的公开 artifact 同时记录
V2 协议和 FP16 优化协议，并将绑定字段命名为 `fp16_optimization_protocol_sha256`。导出引用的
协议哈希与该字段完全一致，但旧 verifier 会因为字段名不同而错误拒绝真实证据。

修改后，verifier 收集顶层 `protocol_sha256` 以及所有以 `_protocol_sha256` 结尾的字符串值，
并要求引用中的精确哈希必须存在于集合中。这样既支持多协议 artifact，又没有降低绑定强度：
错误哈希、缺失哈希仍会 fail closed。

新增测试覆盖：

1. 命名协议字段可通过验证；
2. 引用协议不存在于 artifact 时必须拒绝；
3. 通过后仍必须保持 `INPUT_REQUIRED`、禁止正式质量声明，且结果中不存在 `case_results`。

## 3. 达成效果

新增 pin 和跟踪结果使其他人可以用精确 RAG checkout 复验：

```powershell
./.venv/Scripts/python.exe -m scripts.verify_external_aggregate_contract `
  benchmarks/external_evidence/wixqa_bge_reranker_positive_uncertain_pin.json `
  <exact-rag-checkout> `
  --output docs/results/wixqa_bge_reranker_positive_uncertain_v1/verification.json
```

验证结果为 `AGGREGATE_EVIDENCE_VERIFIED`，但同时保留：

- `payload_granularity=aggregate_only`；
- `formal_case_result_status=INPUT_REQUIRED`；
- `formal_ab_status=NOT_RUN_BY_EVALOPS`；
- `formal_quality_claim_allowed=false`；
- `production_ready=false`。

允许陈述的结果仅限：模拟配置选择集上的点估计、FP16 工程延迟优化，以及历史已消费
ExpertWritten 集上的回顾性点估计。由于所有主要 paired 95% CI 均跨 0，不能陈述统计显著、
盲测泛化、答案准确率提升或无条件生产就绪。旧 MiniLM 负结果继续保留，不被新结果覆盖。
