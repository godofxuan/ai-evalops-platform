# 可信评测产品 v2：最终审核入口

本轮目标：修复 R1–R13，打通 QA / Agent 的可恢复持久实验，提供可操作客户端和独立证据复核。它不是新的 RAG 项目，也不是生产上线或正式质量研究。主执行方案见[完整计划](../plans/trustworthy-evaluation-product-execution-plan.md)。

## 1. 当前交付状态与精确版本

- 工作分支：`codex/trustworthy-evaluation-product-v2`；不合并 main、不改默认分支。
- CODE_SHA：`abfab98056e5526af505551ebde9618b94698f3a`。
- [CODE CI 34117962138](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34117962138)：已核对精确 head_sha，completed/success；quality-and-integration、compose-smoke 均通过。
- DOC_SHA：承载本文及公开演示的后续纯文档/证据提交。其精确 SHA 和自己的 CI 由提交后回执提供；不在文件内伪造自身尚不存在的 SHA，也不递归提交以回填自身哈希。
- `main` 保持 `50af0603ff76615f3cf2c54fba3230e1cee7647f`；旧简历链接/分支/历史合同保留。

CODE 与 DOC 是 **EvalOps 同一仓库的两次提交**，不是把 EvalOps 与 RAG 合并。源码在 CODE 冻结，DOC 只保存说明和可公开证据；最终核对两者的 `app/scripts/tests/deploy/.github` 等源码无差异。

## 2. 本轮到底改好了什么

| 用户原来的问题 | 现在的行为 | 审核位置 |
| --- | --- | --- |
| 脚本退出后不好继续 | 鉴权 API 原子创建父实验及两组现有 Runs；UUID 查询/等待/取消/导出；同键同内容恢复原实验 | [客户端指南](../durable-experiment-client.md)、[API](../../app/api/routes_product_experiments.py) |
| worker 死亡或迟到写入可能污染结果 | 既有 lease/heartbeat/reaper 恢复；accepted attempt 绑定；旧 claim 写入拒绝，已完成题不再执行 | [进程恢复验收](../../tests/product_process_recovery.py) |
| 报告有 hash 但不知道能否复核 | 发布后不可变；默认公共摘要；显式私有材料包含原始输入，可共享聚合器重算，不只验 hash | [独立验证器](../../app/product_experiments/durable_verification.py)、[包协议](../../app/product_experiments/durable_bundle.py) |
| 质量差、执行失败、证据不足混在一起 | CLI 门禁退出码区分；等待超时不取消；报告缺失保留，不取成功交集；FORMAL 标签不授予资格 | [R1–R13 地图](trustworthy-product-validation-map.md) |
| Agent 字段和指标不可信 | 工具/参数类型/预算/终态保留并统一评分；未知成本不造零；引用 precision/recall 分开 | [共享聚合器](../../app/product_experiments/aggregation.py) |
| 新入口难以配置和学习 | 明确 Compose opt-in、真实代码 SHA、数据集映射、幂等重放、恢复模板与私有材料边界 | [使用指南](../durable-experiment-client.md)、[逐步日志](trustworthy-product-execution-log.md) |

平台负责评测执行与证据链，不负责替用户实现 RAG/Agent。它能比较 QA、RAG 及工具调用 Agent；不是只有 RAG，也不是任意任务/任意插件都已支持。

## 3. 验证证据及其边界

### 固定演示：干净 CODE 源码重放

开始运行前 tracked/untracked 工作区干净。生成期间及之后源码 diff 为空，只新增下列公开产物。Windows / Python 3.12.13 / 锁定项目依赖；没有本机 Docker/PostgreSQL，服务级验证由精确 CI 提供。

| 演示 | 输入题数 / 观测 case-arms | 状态 | 公开 manifest SHA-256 |
| --- | --- | --- | --- |
| [QA](../results/trustworthy_product_v2/qa/manifest.json) | 120 / 240 | DEMO_PASS，0 执行错误 | `39a856b5adb6ce697a5a8b0b8f45e734ee71a0467f407a7008058a577ffb10da` |
| [Agent 工具](../results/trustworthy_product_v2/agent/manifest.json) | 120 / 240 | DEMO_PASS，0 执行错误 | `2a778bcabc91d8f76f8b2b7955e0ef48d86f58057c2f7af70113e604164d9e38` |

QA 输入 SHA-256：`563a5063ae06efcd8b4a49729bf3621887b9876ffe34bc66bf41c0b6b2bb916c`；Agent：`d6c10ec43c4f9194c3fc02ffaee2f7457adac0bf8510513761ac9134180d139b`。各自 spec/policy/dataset 由 CODE 下 `benchmarks/product_demo_v1` 与 `benchmarks/agent_tool_demo_v1` 固定；目标均为明确的 deterministic fixture。

每套 240 是两组 case-arm 观测，不是 240 道独立题，更不是 240 次真实模型质量研究。公开包仅 `PUBLIC_PROJECTION_ONLY`，私有原始报告未发布。内部 private_result_sha256 是私有内容摘要，不是公开 result.json 的完整字节 hash。

可在 CODE checkout 的新目录重放；新运行会有新 execution_id / 耗时 / hash，不要求跨运行字节相同。下载同一已发布 durable 报告的字节稳定是另一项合同。

```powershell
uv run --no-sync python -m scripts.run_product_experiment --spec benchmarks/product_demo_v1/experiment.json --output-dir artifacts/review-qa --evalops-sha abfab98056e5526af505551ebde9618b94698f3a
uv run --no-sync python -m scripts.run_product_experiment --spec benchmarks/agent_tool_demo_v1/experiment.json --output-dir artifacts/review-agent --evalops-sha abfab98056e5526af505551ebde9618b94698f3a
uv run --no-sync python -m scripts.verify_product_experiment docs/results/trustworthy_product_v2/qa/manifest.json
uv run --no-sync python -m scripts.verify_product_experiment docs/results/trustworthy_product_v2/agent/manifest.json
```

后两条验证归档包，应在 DOC checkout 运行。验证通过只表示该公共合同完整，不授予正式质量资格。现有 CI 会重放临时 QA 演示；这些新增归档包还单独本地校验，不能把 CI 绿灯说成自动覆盖了所有新归档文件。

### 故障与真实服务

[证据地图](trustworthy-product-validation-map.md)列出完整矩阵：原子两组回滚、8 并发幂等提交、真实 worker 两个阶段强杀、实际租约到期与 reaper、stale writer 拒绝、原已完成题不重跑、提交确认丢失、取消竞争、8 并发不可变导出、存储确认丢失、导出进程死亡、跨租户拒绝、真实部分正文停滞与大小上限。QA/Agent 使用相同持久主路径。

真实 TCP 是本机服务；公共 DNS/peer 元数据是隔离测试夹具，不是公网 TLS 身份认证证明。存储故障是实际本地写入后注入确认丢失，不是云服务故障演练。worker 在外部请求后死亡可能重试调用外部服务；只保证内部接受结果受 fencing 约束，**不承诺外部 exactly-once**。

### 失败记录不能抹掉

上一候选 `87778965024f47c0a9c0dcb5be5fa786f3ad8005` 的 CI 34116820987 失败；完整本地为 1120 passed / 1 failed / 1 skipped。原因是 README/PROJECT_STATUS 更新后遗漏刷新旧清单，规范化换行后的大小仍不匹配。修复只刷新清单和记录原因，保留失败历史与既有校验；此候选不能替代最终成功 CODE。详见日志第十九检查点。

新 CODE 全量本地回归 **1121 passed / 1 skipped，305.60 秒**。Windows 无 symlink 权限的 skip 单独披露，不计作通过。全仓 Ruff lint、640 文件格式检查、223 源文件 mypy 通过。真实 PostgreSQL/Redis/MinIO/Compose 只能依据该 CODE 的远端步骤，不把本机未运行写成 PASS。

另实际执行 `--validate-only`：普通门禁退出 0，`--gate formal` 退出 2，两次 execution_status 均 NOT_RUN、目标调用计划为 0、输出目录不存在。READY 表示输入可用于演示，不代表正式资格。历史清单与 project_scorecard 校验也通过，仍输出 READY_WITH_EXPLICIT_LIMITS / NOT_VERIFIED / NOT_READY_NEGATIVE_SCALING_AND_QUALITY_INPUT_BLOCKED。

## 4. 仍不能写进简历的结论

- 未完成正式 A/B、独立人评或生产部署资格；`formal_quality_claim_allowed=false`、`production_ready=false`。
- 历史 `NEGATIVE_SCALING` 仍成立，本轮没有新容量/SLO/吞吐晋级证据。
- durable 提交仅 DEMO；local 固定 seed 平衡顺序不代表 durable 两组也按随机/平衡顺序执行，不能发布正式延迟公平结论。
- 响应字节、尝试数、并发 admission、总 deadline 是有测试的执行边界；不是模型内部工具调用、硬美元费用、上游物理并发或进程 RSS 的绝对保证。
- hash/重算证明一致性，不独立认证用户声明的目标源码身份。静态输出字段约束不是任意文本绝不泄密的证明。
- 私有 bundle 需要操作者原始数据；没有自动从服务端导出原始题库的新增接口。中断残锁只在确认所属进程死亡后显式处理，不自动删其他 writer 的锁。

## 5. 简历、教学和投递交接

当前简历指针只读核对仍为 `CURRENT_APPLICATION_RESUMES_20260907_R12_RAG_RUNTIME`。本轮不替换 PDF、不改变历史投递状态、不对外提交。

已分别发送完整改进、精确候选/CI 状态和边界至“优化简历内容与结构”“两个项目学习与面试答辩｜RAG + EvalOps”“秋招投递总控（找岗位+定制简历+台账）”。简历任务已回执实际更新 FUTURE_RESUME_EVALOPS_RULES_20260902.md §16、PROJECT_SYNC_RAG_EVALOPS_20260902.md §27；教学任务已回执更新三次事故训练法和最终收口状态。投递任务正在处理既有岗位工作，当前仅确认消息已送达；最终 SHA/CI 仍需提交后补发。不将发送、规划更新、正式 PDF 更新、用户本人掌握混为一谈。

只读核对历史跨仓 evidence 目录与 Final Pair 两份入口文件相对于 main 无差异。仓库首页、main README、main/docs/review/GPT_REVIEW_ENTRY.md 的 HTTP HEAD 均为 200；这是三处实际网络检查，不宣称遍历所有外部链接。新导航使用本地相对路径存在性检查；没有删除或重写历史分支。

建议主线：**可恢复执行 → 同一不可变报告 → 离线证据复核**。教学用一次超时、一次 worker 崩溃、一次篡改重签说明执行终态/质量门禁/证据完整性三种不同的成功。投递只选岗位最相关的一条，不堆测试数字。

## 6. 审核者建议阅读顺序

先读本文与[客户端指南](../durable-experiment-client.md)，再按[证据地图](trustworthy-product-validation-map.md)抽查真实测试，最后看[逐步记录](trustworthy-product-execution-log.md)。核对精确 SHA 的 CI，不借用其他提交结果。旧 [GPT_REVIEW_ENTRY](../review/GPT_REVIEW_ENTRY.md) 与跨仓 Final Pair 保留原始范围，不能当成本轮新功能验收。

审查重点：是否有未经实际证据支持的完成声明、提交/取消/导出竞态是否绕过租户和 attempt 身份、公开投影是否泄露私有字段、私有报告能否真正重算、操作退出码是否被误当质量 PASS。可提出有实际收益的后续问题，不要求为“平台完整”无条件实现 T1–T4。可选扩展、性能归因、公开部署及正式研究的触发条件已写在主计划中。
