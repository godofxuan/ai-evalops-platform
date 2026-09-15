# 验证索引：按证据层级阅读

日志均在交付包 evidence/logs/。源码中的测试名称和命令比“测试总数”更重要。
最终完整套件与身份见 CLOSEOUT_RESULTS.md / DELIVERY_MANIFEST.json；这里同时保留不通过的过程证据。

| 事项 | 反例/失败日志 | 修复后或限定结论 |
| --- | --- | --- |
| heartbeat锁前旧时间 | red-heartbeat-pg.log；最初red-heartbeat.log只是缺数据库 | green-heartbeat-applied；最终test_lease_authorization |
| success/failure等待跨expiry | red-result-expiry / red-failure-expiry | 各Run/Job/Attempt三类真实DB屏障 |
| reaper/commit反向锁 | red-reaper-lock-order-v3；v1/v2为观察器问题 | 固定排程20次；有限覆盖而非无死锁证明 |
| ordinary claim/cancel | red-claim-cancel-isolated；更早一次为旧库残留干扰 | QUEUED更新与RUNNING隐式FK两类均回归 |
| 引用两别名歧义 | red-citation；green-citation-core为错误正则断言 | canonical12控制；local240计划保留1失败；真实QA/Agent持久观察故障 |
| 旧报告兼容 | legacy-local-original-generate / legacy-local-current-verify | 原ZIP源码生成v2，新load_evidence按旧规则重算120题 |
| Windows进程模型 | product-durable-v3 / full-integration-final | selector child + Popen线程生命周期；telemetry-lease-controls 37 passed |
| Docker上下文漏排除证据 | red-build-context；full-unit-final前后指纹不同 | green-build-context 30 passed；真实源码变动仍改变指纹 |
| matrix恢复排程 | full-integration-v2 | 先DB确认retry到期；matrix-readiness及最终matrix；不延长重试预算 |
| 外部依赖文件缺失 | full-unit-v2 / full-integration-v3 / release-final / demo-qa | 受影响运行中止；专属.venv由锁文件重建；最终验收使用isolated命名 |
| 固定checker正向 | release-isolated.xml/log | 37 passed，0 skip，0模型调用 |
| checker篡改/缺料 | release-tampered-isolated / release-missing-isolated | 预期非零，分别source_hash_mismatch / missing_source |
| 原始跨家族包 | cross-family/REPLAY_RECEIPT.json及两日志 | 14666成员；BFCL/RAGBench四模型历史报告重算；0新增调用 |
| 新演示 | demo-qa-isolated / demo-agent-isolated / demo-analysis-verify-isolated | 各120题合成样例；LOCAL_RECOMPUTED_NOT_PROVENANCE |
| 历史清单/评分卡 | historical-manifest-verify / historical-scorecard-verify | 保留原决定，不自动升级release/production |

## 如何看一次“失败”而不混淆结论

- red日志中测试断言失败，可能是**成功复现旧缺陷**；须读文件名、源码时点与具体断言。
- 依赖缺失、权限不足、无MinIO是环境边界；不伪造产品通过。
- matrix的质量结果EXECUTION_FAILED是协议预期，测试通过代表计账/恢复/拒绝行为符合合同。
- 调试重跑都是同一合成协议的工程验证，不是新的独立质量样本，不择优计算平均分。
- 最终matrix的product_execution_code_sha若来自固定fixture e×40，只是测试输入，不是构建认证；交付CODE_SHA与逐文件清单才标识实际实现。提交后另有带实际CODE_SHA的matrix-code验收，若未提供则不能自行补称存在。
- 旧CrossFamily推理时点的代码/配置身份属于原ZIP，不反标为新CODE_SHA。原ZIP保留所有原件，重算日志仅是此次复核。
- 本轮未运行随机交错100次或新吞吐性能实验；历史NEGATIVE_SCALING不被抹掉。
