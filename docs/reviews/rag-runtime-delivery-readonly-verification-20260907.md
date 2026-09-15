# RAG runtime delivery：固定公开证据只读复核

复核日期：2026-09-07。范围：RAG 任务交付的固定公开 Git 对象，未修改 RAG 工作区，未运行模型，未读取私有运行产物，未创建或导入 EvalOps CaseResult。

## 身份与在线状态

- RAG CODE_SHA：`0bca9534fd0cf9d4b02d65c1c46de1a8fec67a4f`。
- RAG EVIDENCE_SHA：`e276209bae4544ad54405a282448ab07cf01d8e5`。GitHub Git commit API 已确认该完整提交存在。
- [固定审核入口](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/blob/e276209bae4544ad54405a282448ab07cf01d8e5/docs/review/runtime_delivery_20260905/RESULTS.md)。本次原始字节从该 SHA 的 Git blob 读取，不使用变化中的工作区文件。
- [代码精确 CI 34089355411](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/34089355411)：本次在线查询 completed/success。
- [证据精确 CI 34090622842](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/34090622842)：首次查询 in_progress；收到完成通知后再次查询该精确 SHA，确认 completed/success。RAG 任务报告清洁检出 3650 passed / 36 skipped 和导出重放 VERIFIED 775/800，但这些没有由本次 EvalOps 复核执行，仍区别于本次独立公开数据重算。

## 字节与数量

manifest schema 为 runtime-delivery-evidence/1；服务行为 runtime-service-contracts/1；检索材料为 retrieval-replay-measurements/1。

| 固定对象 | SHA-256 / 结果 |
| --- | --- |
| manifest.json | `357a390349236e205590dd853429027339df4c405c7564a3f61f5e6c3987dd00` |
| metrics.csv | `a67bbc64c322a58c307ede4af2b169a2404eedfcab531780b0f71626f07f0d53`，匹配 manifest |
| service_cases.json | `47a7824dec7e5ff5a40300c0bbacf119899765afc9a16da4be8ce51fda3a997e`，匹配 manifest |
| service_comparison.json | `ec86eb4d9f1bd9056370cdc055cdff721190fa43ba05833603d68f44ed7ce2ab`，匹配 manifest |
| retrieval_evidence.json | `e32443f1379131c2411d3f474ebd25045a0937482ec3d5ef03563832dcb8e456`，本次独立计算；不在上述服务 manifest 的三文件列表中 |

manifest 中 exporter_sha256 与该证据提交的 scripts/export_runtime_delivery.py 精确字节一致。

服务总计 775 行：680 main、35 warmup、60 resource（resource1/2/4 各 20）。三个 run 的 main 分别 360/240/80，warmup 15/10/10，resource 36/24/0，逐项匹配 manifest。main 的 (run_id, profile, repeat, case_id) 680 个键唯一，只有 40 个不同 case_id。

预热/资源请求会重复公开用例标识：全部 775 行按上述字段加 kind 只有 702 个不同组合。最初把所有辅助负载也要求唯一的诊断断言失败，检查后确认它们是重复同用例的负载记录，改为单独验证主请求唯一性并保留全部辅助行。不能宣称 775 独立样本，也不能据此伪造每次请求的公开 UUID。

## 独立聚合重算

依据固定 exporter 的分组语义，以独立 NumPy 数值计算复核 CSV，不调用 exporter 的聚合函数，不重写 CSV。遵循只读表格核验原则，计数精确相等，延迟比较绝对容差 1e-9 ms、相对容差 1e-12，比例容差 1e-12。

- CSV 全部 87 个分组：按 run_id/profile/kind，分别核对 all/contract_complete/contract_failed 的 n、complete、已知安全失败数、model_calls/retries/errors，以及 client_ms 的 mean/p50/p95。百分位为线性插值，空分组保持空值，全部一致。
- service_comparison 两个修复配对：按 case_id/repeat 对齐原版与 repair，各 120 对。Hybrid 保留 77、改善 10、退化 8、仍失败 25；raw20 保留 85、改善 11、退化 5、仍失败 19。与文件一致。
- 检索 800 行、4 个 profile 各 200 行，(question_id, profile) 唯一。每组 6 个质量均值、失败数和不含 shared embedding 的延迟 p50/p95 全部与 summary 一致。
- 全部服务行保留 9 次历史 HTTP 503；readiness run 为 0 次 503。不能抹掉历史失败后宣称全历史零失败。

本次结果为 `PUBLIC_ROWS_AND_AGGREGATES_VERIFIED`。没有访问私有 rows/completion，所以私有执行重放为 NOT_PERFORMED；没有再次调用真实模型，所以这不是独立真实执行重现。

## EvalOps 可使用与不可使用的结论

可归档：固定公开字节摘要、主/预热/资源计数、公开行到聚合一致性、受限合成服务合同结果与检索结果。声明中的代码 SHA 与运行身份仍不能仅凭公开自报字段获得独立运行认证。

不可升级：不是 enterprise.agent-run/1.0 轨迹，不从聚合值生成 CaseResult，不是正式质量 A/B 或人评准确率，不证明零幻觉、零安全风险、生产 SLA。检索 p95 不含共享 embedding，不能叫 API p95；680 主请求也不是 680 独立题。

此次不新增导入器，不修改两个项目默认策略，不改变 main、旧证据或已投简历链接。EvalOps 自身持久实验提交、共享预算、有效 attempt 导出与故障 E2E 仍需继续实施，不能由 RAG 证据通过替代。
