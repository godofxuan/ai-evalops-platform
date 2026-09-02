# 项目负责人一页入门：AI EvalOps 到底在做什么

如果只记住一句话：**它不是另一个聊天机器人或 RAG，而是批量检验这些 AI 系统的后台平台。**

## 一个具体例子

假设你有旧版 RAG 和新版 RAG，想知道新版是否更好。你准备 120 个问题，然后让两版系统分别回答。
真正困难的并不只是调用 240 次接口：中途可能超时、Worker 崩溃、同一任务被重复领取、旧 Worker
在恢复后写回过期结果、一个大客户占满队列，或者实验结束后无法证明当时到底用了哪个代码版本。

AI EvalOps 负责把这件事变成一个可恢复、可审计的流程：

```text
上传版本化数据集
  → 创建一次 Evaluation Run
  → 每个问题生成一个持久 Job
  → PostgreSQL 公平调度给 Worker
  → 每次执行形成一个有 lease/version 的 Attempt
  → 保存答案、引用、工具调用、失败与 Agent 轨迹
  → 自动指标 + 双人盲审
  → 用精确 Git SHA、数据集 SHA 和证据清单决定能否发布
```

## 五个核心概念

| 概念 | 通俗解释 | 为什么不能省略 |
| --- | --- | --- |
| `Dataset Version` | 本次考试的固定试卷 | 防止跑到一半题目被改了 |
| `Run` | 一整场评测 | 绑定目标版本、评测器和试卷 |
| `Job` | 一道需要完成的题 | 可以排队、取消、重试和恢复 |
| `Attempt` | 某个 Worker 对这道题的一次执行 | 区分正常重试和过期 Worker 的迟到写入 |
| `Artifact / Evidence` | 答案、引用、轨迹、指标与来源证明 | 让比较结论可复核，而不只剩一张截图 |

## 为什么它是后端/分布式系统项目

- PostgreSQL 是状态权威，不靠单进程内存记住队列。
- Worker 用 lease、heartbeat 和 fencing；失联任务由 Reaper 回收，旧 Attempt 不能覆盖新结果。
- 多租户调度使用持久公平轮次，避免热门租户长期挤压其他租户。
- Outbox/Dispatcher 让审计事件和业务事务保持可追踪的一致性。
- Agent/RAG 通过框架无关的轨迹合同接入；平台不复制被测 RAG 的检索实现。

## 目前已经做好的部分

- 多租户身份、不可变数据集、Run/Job/Attempt 状态机和幂等创建。
- PostgreSQL 并发领取、租约续期、崩溃恢复、迟到写入拒绝和租户公平性回归测试。
- Agent 轨迹、引用/工具/终止状态投影、双层 SHA-256、不可变 Artifact 和审计链。
- MCP 本地 stdio 控制面、自动评测、回归比较、双人评审机制和证据化 CI。
- 跨 RAG/EvalOps 精确 SHA 互操作合同已在受控样例上通过。

这些成果足以把项目作为**有明确边界的工程作品集**。它们不等于“生产就绪”。

## 当前正在解决什么

历史冻结实验发现，从 4 个 Worker 增加到 8 个 Worker 时，三个工作分布的吞吐比低于预注册的
`0.95` 下限。项目因此诚实保持 `NEGATIVE_SCALING`，没有通过修改阈值假装成功。

当前分支只允许一个候选改动：已有公平许可时先直接领取，避免每个成功领取都先做一次额外的
“是否存在活动轮次”数据库事务。真实 PostgreSQL 门固定使用 q1000、sample100、batch1、四种分布、
1/2/4/8 Workers 和四次重复。实验已完整执行，四个 w8/w4 比值为 `0.7045 / 0.7919 / 0.7063 /
0.8640`，全部低于 `0.95`。这说明候选不足以解决问题；它不会合入 `main`，也不会继续看结果调参。

同时，正式答案质量门已经实现，但只有拿到干净的 RAG baseline/candidate 精确 SHA、120 个共同案例
的真实输出和两位真实评审后，才能从 `QUALITY_EVIDENCE_INSUFFICIENT` 前进。

## 现在能说和不能说什么

可以说：

- 设计并实现了多租户异步 AI/Agent 评测编排后端；
- 用 PostgreSQL lease/heartbeat/fencing 处理 at-least-once 执行下的恢复和迟到写入；
- 建立精确源码、数据集、Agent 轨迹与评测结果的可验证证据链；
- 在冻结性能门失败时保留负面证据并阻止发布。

不能说：

- “exactly once”“线性扩展”“生产级”“已正式发布”；
- “新版 RAG 质量显著提升”，因为正式 A/B 和真实双人盲审尚未完成；
- 用机制测试或合成样例冒充线上容量、用户实验或安全认证。

## 建议学习顺序

1. 先读本页并手画上面的请求流。
2. 阅读 [`docs/02_domain_model.md`](../02_domain_model.md)，弄清 Run、Job、Attempt 的区别。
3. 阅读 [`app/jobs/claiming.py`](../../app/jobs/claiming.py) 和并发测试，理解公平领取。
4. 阅读 [`docs/learning/AGENT_EVALOPS_TUTORIAL.md`](AGENT_EVALOPS_TUTORIAL.md)，理解 Agent 证据层。
5. 最后读 [`docs/review/PROJECT_SCORECARD.md`](../review/PROJECT_SCORECARD.md)，练习区分作品集、发布和生产门。

判断自己是否真的理解：不看文档，解释“为什么 Job 和 Attempt 不能合成一张表”，以及“为什么 CI
成功不一定代表发布门通过”。
