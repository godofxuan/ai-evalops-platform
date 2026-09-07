# F1–F5 执行链路与边界

基线 CODE abfab98056e5526af505551ebde9618b94698f3a，DOC b122a6d7394146422c8c153e33531f81241c8280。原工作区未切换；专用 worktree 从 DOC 创建。2026-09-07 Python 3.12.13、uv.lock SHA256 1a83041db8aae7ac85020405733e1638efa89ae1f4fc8618184b9864f54ffee6；uv sync --locked --all-groups 实际成功，跨磁盘硬链接不可用时 uv 自动复制，没有更新锁。

| 路径 | 实际组件及校验点 | 错误落点 / 报告取数 | 测试替代边界 | 初始验证 |
| --- | --- | --- | --- | --- |
| A local fixture | _FixtureProvider.execute → ProviderResult → run_experiment → aggregate_product_observations | measure 捕获目标错误；原 ProviderResult 漏长度，聚合才构造 ProductCaseMeasurement | 仅合成 fixture，无外部目标 | F1 超长在聚合崩溃、CLI 2/无包，已复现 |
| B local HTTP | HTTPRAGTarget.execute_case → normalize_product_observation → ProviderResult.from_target → 同聚合 | 目标错误进入 CaseExecutionFailure，原题集合保留 | HTTP/DNS 外部边界注入，另有真实 loopback TCP | 原终态矛盾可通过规范化，待新增回归 |
| C durable | create_app 鉴权 API → 原子父实验/双 Run → EvaluationWorker._process_claim → ProductQAEvaluator/ProductAgentEvaluator → SQLAlchemyFailureCommitter 或 ResultCommitter | evaluator 在 commit_success 前；ResultReader repeatable-read 快照 → build_durable_report → 不可变发布 | 不替换数据库/worker/聚合/发布；仅合成 HTTP 目标 | 本机无 Docker；新精确 CI 必须提供 PostgreSQL 验收 |
| D offline private | verify_durable_report → PrivateDurableReport → build_durable_report → ProviderResult 恢复 → 共用 scorer → 完整比较 | 非法旧观测拒绝新发布/重算；不改原始 accepted 行或历史包 | 无网络、无数据库；输入为合成私有包 | 旧 F3 local 探针不能证明此层被绕过 |

基线三个探针已在上述 3.12 锁定环境实际重跑。F1：worker OBSERVED，100001 字符，聚合 ValidationError，CLI 输入错误 2。F2：合法零工具输入，failed/answer 冲突得到 completion=1，100 条 candidate 仍 DEMO_PASS。F3：重签普通摘要后的 local 私有语义篡改仍接受。脚本退出 0 仅表示诊断完成。新测试使用正常 conftest，不关闭插件或跳过父配置。

根因排序：共享答案合同缺失；终态映射和一致性分离；fixture 模型异常未在目标边界转换。每一项以真实行为负例先红后绿，不放大后段上限。F3 只披露范围，不建设 local 语义重算器。
