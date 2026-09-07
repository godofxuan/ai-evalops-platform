# 可信评测产品 v2：验收证据地图

这是行为与证据的对应关系，不是测试数目排行榜。第十五至十七检查点各自精确 CI 已成功；新加入的 Agent 全路径和 Compose 显式启用仍待实现冻结后的 CI，不能借用上一提交的结果。

## 精确回执

| 检查点 | 源码 SHA | CI |
| --- | --- | --- |
| 15：客户端与离线重算 | a10c785f5e88d9c53c3348d037b3e78cf88c2c47 | [34112208092](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34112208092) success |
| 16：真实 worker 强杀与恢复 | 6d8e68dcc466fba181be96df0f7bfe5cb7d0a052 | [34113351106](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34113351106) success |
| 17：剩余故障边界 | 799ba5acbacf5a529472caf8b27083542c5d23b2 | [34114567320](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34114567320) success |

## R1–R13

| 要解决的问题 | 实际行为与复核入口 |
| --- | --- |
| R1 正式资格 | [runner 回归](../../tests/unit/product_experiments/test_runner.py)：FORMAL 标签不能让 fixture 获得资格；缺证据在调用前返回 INPUT_REQUIRED |
| R2 Agent 响应 | [真实 socket 目标](../../tests/unit/targets/test_loopback_product_target.py)保留工具、错误、终态和费用；[worker evaluator](../../tests/unit/evaluators/test_product.py)使用共用评分 |
| R3 退出码 | [local CLI](../../tests/unit/scripts/test_product_experiment.py)覆盖公开状态；[durable CLI](../../tests/unit/scripts/test_product_experiment_client.py)区分操作成功/等待超时；[下载包测试](../../tests/unit/product_experiments/test_durable_bundle.py)证明文件生成后质量证据不足仍退出 2 |
| R4 聚合合同 | [aggregate 回归](../../tests/unit/product_experiments/test_aggregate_contract.py)拒绝重签 hash 后的 schema/题数/协议/声明不一致；不虚构逐题 CaseResult |
| R5 缺测与指标 | [runner](../../tests/unit/product_experiments/test_runner.py)、[纯 evaluator](../../tests/unit/product_experiments/test_evaluators.py)：未知费用不造零、引用 precision/recall 分开、工具参数类型敏感 |
| R6 持久入口 | [真实数据库主路径](../../tests/integration/test_product_experiment_persistence.py)从鉴权提交到现有 worker、SDK 查询、不可变报告和原始数据重算，不靠 SQL 手工置入结果冒充完整产品 |
| R7 完整性 | [local manifest](../../tests/unit/scripts/test_product_experiment.py)拒绝缺 arm/错题；[durable report](../../tests/unit/product_experiments/test_durable_report.py)拒绝缺 accepted attempt/配置错配；[durable bundle](../../tests/unit/product_experiments/test_durable_bundle.py)要求完整源、固定文件和重生成 HTML |
| R8 故障与质量 | 有效差答案进入质量门禁；传输/超时与内部错误进入安全原因码；[存储确认丢失测试](../../tests/unit/product_experiments/test_durable_report.py)不发布虚假成功 |
| R9 标签隔离 | 真实 socket 请求只包含 question 和明确 public_context；原始答案、工具预期和 fixture 标签保留在评测侧 |
| R10 有界执行 | [spec](../../tests/unit/product_experiments/test_spec.py)、[submission](../../tests/unit/product_experiments/test_submission.py)、真实慢流、共享 claim admission 和总 deadline 回归；没有做容量/SLO 或硬美元保证 |
| R11 身份 | 父实验/两组 Run/Job/Attempt 分离；同键同内容重放；[响应丢失测试](../../tests/product_controls_faults.py)返回原 UUID；恢复只绑定新 accepted attempt |
| R12 比较目的 | [runner](../../tests/unit/product_experiments/test_runner.py)区分 qualification/non_regression，覆盖 100%→95% 退化和固定 seed 顺序；[diagnostics](../../tests/unit/product_experiments/test_diagnostics.py)展示缺失与切片 |
| R13 零工具 | 空 allowlist、零预算、正确拒绝、越权与 bool/number 差异有定向回归；新完整 Agent 数据库路径使用合法零工具 case，待其自身 CI |

执行顺序边界：固定 seed 的平衡安排属于 local runner。durable 路径沿用既有调度器，记录实际 attempt 时间与身份，不保证跨两组的随机/平衡执行顺序；两种模式共享评分语义，不等于延迟实验条件完全相同。当前持久提交仅支持 DEMO，不用未控制顺序的数据发布正式延迟公平结论。

## S5 故障矩阵

| 场景 | 证据层级和实际断言 |
| --- | --- |
| 两组创建中断 | 真实 PostgreSQL：第二组插入故障导致整体回滚，无可运行半对实验 |
| 并发同键提交 | 真实 PostgreSQL/API：8 个相同提交返回同一父实验与两组 Run；改内容冲突 |
| claim 后 worker 被杀 | [真实 spawn/kill](../../tests/product_worker_process.py)：已提交 lease 实际到期，reaper 恢复，新 attempt 2 完成 |
| HTTP 完成后 worker 被杀 | 真实本机 TCP + spawn/kill：外部请求重复一次；内部最终只有一个有效结果，已完成其他题不重跑 |
| stale writer | [恢复测试](../../tests/product_process_recovery.py)：旧 claim 的 stale poison 被 LeaseLostError 拒绝，报告仍只绑定新 accepted attempt |
| 提交确认丢失 | 真实 API/数据库，网络边界在取得 202 后抛 ReadError；同键重试返回原 UUID |
| 取消与完成竞争 | 真实父实验 cancel 与 owned result commit 并发；1 个在运行结果可完成、3 个待执行任务取消，最终实验不获得质量 PASS |
| 并发导出 | 真实数据库 8 个导出者复用相同发布引用与字节；不同报告拒绝覆盖 |
| 一组失败/缺题 | 全集合保留缺失，不取成功交集伪造完整 PASS |
| blob 确认丢失 | 实际本地对象写入 + 受控确认故障；不登记发布成功，重试可恢复；不是云服务故障实测 |
| 导出进程被杀 | 真正 OS kill 于文件系统最终 rename 前；正式目录不存在，残锁不被其他 writer 删除；确认自身进程死亡后显式恢复 |
| 租户隔离 | 新提交、查询、取消、公开/私有导出经过实际鉴权；跨租户隐藏对象存在性 |
| 慢流与超限 | 真实 TCP 的首字节后停滞触发 timeout，超限触发 response_too_large；不靠耗尽内存验证 |
| Agent 全流程 | 新参数化与 QA 采用同一公开提交/worker/恢复/报告流程，真实数据库验证待最新实现 CI；不提前写成功 |

这些证明受控条件下的工程机制，不证明全部公网部署、真实外部工具 exactly-once、独立盲评、生产容量或性能伸缩性。

## 最终收口尚需

实现冻结 CODE_SHA 与自己的完整 CI；干净源状态的说明重放；单独文档/证据 DOC_SHA 与自己的 CI；远端、工作区、公开链接和跨任务回执核对。详见[执行计划](../plans/trustworthy-evaluation-product-execution-plan.md)和[逐步日志](trustworthy-product-execution-log.md)。
