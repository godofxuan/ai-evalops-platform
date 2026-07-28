# Target 与 Evaluator 语义

## 分层合同

一次成功执行分为四层：

```text
immutable EvaluationCase
  → EvaluationTarget.execute_case()
  → TargetResult
  → Evaluator.evaluate()
  → EvaluationResult
  → fenced CaseResult commit
```

Target 负责与被测系统通信，不判断答案正确性。Evaluator 只消费已经成功且结构化的
`TargetResult`。数据库提交再次核对 lease owner、version、状态和过期时间；外部调用成功不
代表 Worker 仍有权写最终结果。

## 可复现输入

Worker 不重新扫描 Dataset artifact，而是读取创建 Run 时写进 Job 的不可变
`case_payload_json`。`EvaluationCase` 固定包含：

- `case_id`；
- `question`；
- `expected_answer`；
- `metadata`。

Run 同时绑定 dataset hash、Target/Evaluator 配置 hash、类型和版本。Phase 4 为 Run 增加了
显式 `evaluator_type`。原始最低字段清单只有 `evaluator_config_json` 和
`evaluator_version`，无法无歧义选择实现。替代方案是把类型藏进配置 JSON，但那会弱化查询、
迁移和审计，因此采用显式列；迁移对历史行先填 `execution`，随后移除 server default，新
Run 必须明确写入。

## MockTarget

MockTarget 完全由 Run 配置或 `case.metadata.mock` 决定，不使用随机数。支持：

- 固定延迟；
- 固定 answer/citations/sources/trace/token usage；
- timeout；
- HTTP 429/500；
- invalid JSON；
- 永久失败；
- 前 N 次返回 503，下一次成功；
- 执行前后取消检查。

测试注入 fake sleeper，不使用真实 sleep。按 case 覆盖配置便于在同一 Dataset 中稳定构造成功、
重试和永久失败样本。

## HTTPRAGTarget

支持：

- HTTPS `base_url` 与相对 endpoint；
- question 字段映射；
- answer/citations/sources/trace/usage 点路径映射；
- timeout；
- bearer token 的环境变量引用；
- Job/Attempt 追踪请求头。

认证值不进入 Run 配置：配置只保存 `auth_env_var` 名称，Worker 执行时从环境解析。直接
`authentication` 对象会因 extra-forbid 被拒绝，避免把明文 Token 固化进数据库或幂等 hash。

### SSRF 边界

第一版安全策略：

- 仅允许 HTTPS；
- endpoint 必须是无 authority、query、fragment 的绝对路径；
- hostname 必须精确出现在 `allowed_hosts`；
- 拒绝 localhost 和非公网 IP literal；
- 每次请求前解析全部 DNS 地址，只要包含非公网地址就拒绝；
- URL 不允许 userinfo。

这能阻止常见的 loopback、link-local、RFC1918、URL authority 注入和显式私网地址，但不能
消除 DNS 检查与 httpx 实际连接之间的重绑定时间窗口。更强方案需要自定义 transport 固定已
验证地址且正确处理 TLS SNI/Host，或由网络层 egress proxy 强制目的地策略。当前实现不能被
描述为“完全防 SSRF”，部署时应叠加网络出口控制。

响应正文和认证信息不会进入异常消息；稳定错误只包含错误类别与 HTTP 状态。

## Evaluator

### ExecutionEvaluator

只记录操作事实：

- `execution_success`；
- latency；
- input/output tokens；
- attempt count；
- 是否重试后成功。

### BasicAnswerEvaluator

指标故意使用带 `lexical_` 前缀的名称：

- `lexical_exact_match`；
- `lexical_normalized_exact_match`；
- `lexical_keyword_coverage`；
- `has_answer`；
- `has_citations`。

normalized exact match 只做 Unicode NFKC、case-fold 和空白折叠。关键词覆盖只在人工数据显式
提供 `metadata.keywords` 时计算；没有标签返回 `null`，不擅自从 expected answer 拆词。

这些指标不能被称为语义准确率。没有可靠人工标签或经验证的语义评测器时，词法重叠只能表示
表面一致。

## Case Result 提交

数据库唯一约束同时保护：

- 每个 Job 最多一个结果；
- 每个 Run/case 最多一个结果。

提交事务先锁定满足以下条件的 Job：

- ID 与 Run 匹配；
- 状态为 running 或 cancelling；
- lease owner 匹配；
- version 匹配；
- lease 尚未过期。

然后校验 Attempt 仍未完成，通过显式状态机进入 succeeded，写 CaseResult、完成 Attempt、
清理 lease、写 AuditEvent，并原子增加 Run 的成功计数。竞争取消时，cancelling 可以合法
完成；旧 Worker、旧 version 和过期租约均得到 `LeaseLostError`。

该设计提供幂等结果持久化，不提供 exactly-once 上游执行。外部 Target 可能已处理两次请求，
数据库只保证最终结果不会被旧世代覆盖。

## 当前验证边界

本机验证了 deterministic Mock、HTTP request/response mapping、SSRF 输入边界、Evaluator
指标命名、Worker 成功流水线、结果提交 SQL 条件、ORM 唯一约束和 offline migration。
真实 PostgreSQL 下的结果竞争合同已加入并明确 skip；本机不能声称它已经实际通过。
