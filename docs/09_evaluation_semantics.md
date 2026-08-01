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

- 操作员维护的版本化 Registry 与 tenant 只读 `target_id` 选择；
- HTTPS 443 `base_url` 与相对 endpoint；
- question 字段映射；
- answer/citations/sources/trace/usage 点路径映射；
- timeout；
- bearer token 的环境变量引用；
- Job/Attempt 追踪请求头。

tenant 的 HTTP config 必须恰好是 `{"target_id": "..."}`，且请求 version 必须与 Registry
version 精确一致。未知 ID、版本不一致、tenant 提交 URL 或额外字段都会在 Dataset I/O 前失败。
操作员配置在 Run 创建时经过安全校验并冻结为执行快照；Registry 后续变化不会静默改变已有
Run。除独立凭证值轮换外，执行配置变化必须由操作员提升 version；平台保存 target config hash，
但不能自动证明外部版本标签遵守该纪律。MockTarget 不走 Registry，继续用于内部和确定性测试。

认证值不进入 Registry 或 Run 配置：配置只保存 `auth_env_var` 名称，Worker 执行时从独立进程
环境解析。直接 `authentication` 对象会因 extra-forbid 被拒绝，避免把明文 Token 固化进数据库、
幂等 hash、源码或日志。Registry 的环境变量不会自动变成凭证环境变量，部署者必须把被引用的
变量单独注入 Worker。

### SSRF 边界

当前应用层安全策略：

- Registry 由操作员维护，tenant 无权提交或覆盖 URL、host allowlist、认证变量和 timeout；
- 仅允许 HTTPS 默认端口或显式 443，不允许其他端口；
- endpoint 必须是无 authority、query、fragment 的绝对路径；
- hostname allowlist 由平台从 Registry `base_url` 派生，执行快照只允许精确 hostname；
- URL 不允许 userinfo、query、fragment、编码 IP、纯十进制 IP 或越界 hostname label；
- hostname 必须是 ASCII；IDN 由 operator 显式提供规范化 punycode，避免依赖隐式 IDNA 路径；
- 不跟随 3xx 重定向，所有 300 及以上响应进入稳定 HTTP 错误分类；
- 每次请求解析全部 A/AAAA 地址，只要包含 loopback、私网、link-local、metadata、unspecified、
  reserved、multicast 或 IPv4-mapped IPv6 就拒绝；原生公网 IPv4/IPv6 可以使用；
- DNS 解析本身也受 target `timeout_seconds` 约束，不会无限期占用 Worker；
- 选择一个已验证地址，以数值 IP 发起请求，避免 transport 再次按 hostname 解析；
- HTTP Host 与 TLS SNI 仍使用 Registry 中的原 hostname；
- 在读取响应正文前，从 HTTPX/HTTPCore `network_stream` 取得实际 peer；缺失、端口不是 443、
  非公网或不等于所选地址都以 `target_peer_mismatch` 失败关闭；
- 内建客户端禁用环境代理，避免 `HTTP_PROXY`/`HTTPS_PROXY` 绕开数值 IP 连接合同。

数值 IP 固定与实际 peer 校验关闭了旧实现的“检查 hostname 后由客户端再次解析并连接”窗口，
但不能证明所有操作系统、NAT、透明代理、容器网络、依赖升级和云网络策略都不可绕过。生产环境
仍必须用防火墙、NetworkPolicy、安全组或受控出口做第二层限制，并锁定/回归 HTTPX 与 HTTPCore
版本。会隐藏 `network_stream` peer 元数据的自定义 transport 或代理会失败关闭，而不是回退到
旧模式。因此当前实现仍不能被描述为“完全防 SSRF”或通过安全认证。

响应正文、URL、IP 和认证信息不会进入稳定 Target 异常；配置校验也切断可能含明文输入的底层
异常链。旧的已完成结果仍可读取，但不含 `target_id` 的旧排队 HTTP 快照会在 Worker 构造 Target
时失败关闭，不做静默迁移。本轮不需要数据库 migration。

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

本机验证了 deterministic Mock、HTTP request/response mapping、Registry 解析、数值 IP/Host/SNI
请求合同、真实 HTTPX peer 元数据时序、SSRF 输入边界、Evaluator 指标命名、Worker 成功流水线、
结果提交 SQL 条件、ORM 唯一约束和 offline migration。
真实 PostgreSQL 下的结果竞争合同已加入并明确 skip；本机不能声称它已经实际通过。
