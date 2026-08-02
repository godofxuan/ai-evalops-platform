# Phase 1 安全边界

## 1. 身份边界

- 客户端只提交 Bearer API Key。
- 服务端解析安全 prefix、查询候选记录并验证 scrypt hash。
- tenant ID 来自已验证记录，不来自 JSON、query 或 path。
- 原始 API Key 只在创建脚本的标准输出显示一次。
- 日志禁止记录 Authorization、完整 key、hash 或 salt。

## 2. 统一认证失败

缺失、错误、撤销、过期和 inactive tenant 对外均表现为：

```json
{
  "error": {
    "code": "invalid_api_key",
    "message": "Authentication credentials are invalid."
  }
}
```

这样不能完全消除时序侧信道，但避免直接泄露 key 或 tenant 状态。未知 prefix 也执行 dummy scrypt。

## 3. Tenant 隔离

- Dataset 创建强制写 principal.tenant_id。
- Dataset/version get 和 upload 同时过滤 tenant ID 与资源 ID。
- 跨 tenant 与不存在都返回 404。
- 本阶段没有管理员跨 tenant API。
- Dataset Version、Run、Run-owned Artifact Reference 和人工复核记录使用包含 tenant 的
  复合外键，防止单列父 ID 与行内 tenant 来自不同租户。
- Case Result 与 Human Review Task 使用 `(job_id, run_id)` 复合外键，防止同 tenant 内也
  把记录挂到错误 Run 的 Job 上。

应用仍先执行 tenant-scoped 查询，数据库复合外键提供第二道写入完整性防线。当前不是
PostgreSQL RLS：复合外键阻止矛盾归属行，却不会自动给任意 SELECT 注入 tenant 条件。
未来新增 repository 方法时仍必须有跨 tenant 负面测试。

### 3.1 Human Review capability

- `can_create_review_tasks` 与 `can_review` 都保存在 API Key、默认 false，并从认证记录进入
  Principal；客户端不能提交权限值；
- 前者只允许创建/扩展 Task，后者只允许 reviewer list/submit/adjudicate；
- ordinary、reviewer-only credential 创建 Task 都返回独立 403，且检查发生在数据库和
  artifact I/O 前；
- creator-only credential 不会因此获得 reviewer 权限；
- 管理员 CLI 必须显式使用 `--review-task-creator` 或 `--human-reviewer`，建议为职责分离
  使用不同 credential。

这两个布尔 capability 是当前工作流的最小权限边界，不是完整 RBAC、组织审批或通用 scope
系统。数据库 FK 保证 creator 同 tenant，但不能替代服务入口的 capability 检查。

## 4. 上传边界

- 只接受明确 allowlist 中的 JSONL media type；
- 读取 `max_bytes + 1` 检测超限；
- 限制行数和单行大小；
- 严格 UTF-8 和 JSON object；
- case ID 必须唯一；
- 错误响应不回显整行敏感内容；
- 原始文件名不参与 storage path；
- 验证后先做 tenant-scoped dataset 存在性检查，不存在或跨 tenant 时不写 artifact；
- 落盘后仍在短事务内按 tenant 重新锁定 dataset，避免预检查与提交之间的竞态。

## 5. 文件系统边界

- storage path 由服务端 SHA-256 生成；
- 数据库只保存相对路径；
- artifact root 在初始化时 resolve，后续路径段只能是固定长度十六进制摘要；
- 两位摘要目录若是符号链接则拒绝；
- 临时文件和最终文件都位于同一目录/文件系统；
- flush + fsync 后重新读取确认临时文件大小和 SHA，再进行 create-only 原子发布；
- 无论成功或失败都在 `finally` 清理临时文件；
- 用户输入不能包含 `../` 或绝对路径并进入存储 API。

## 6. Artifact 所有权边界

- 全局 `artifact_blobs` 只表示物理内容，不表示任何 tenant 有权读取；
- `artifact_references` 才保存 tenant、可选 Run、类型和 media type；
- 读取必须用 reference UUID 同时过滤 tenant 和可选 Run，再 join blob；跨 tenant、错误 Run 与
  不存在共用同一个 not-found 结果，并且在失败时不触碰物理文件；
- 同一 tenant 的两个 Run、以及两个不同 tenant，可以拥有不同 reference 并共享同一 blob；
- 删除一个 reference 不删除仍被其他 reference 使用的 blob；最后一个 reference 删除后才清理
  blob metadata 和经过摘要校验的物理文件；
- 缺失或摘要不符的物理文件读取失败关闭，不把数据库 metadata 当作完整性证明；
- 已知 SHA 的 orphan 清理必须先由数据库确认没有 reference，不能由客户端直接按 SHA 请求。

数据库事务与本地文件删除不是分布式原子提交，本地 store 也不支持多个 API 主机共享。当前
合同优先避免删除仍被授权引用的内容；多主机部署需要对象存储生命周期或等价协调机制。

## 7. HTTP Target 出口边界

- tenant 只提交操作员 Registry 中的 `target_id`，不能提交 URL 或 allowlist；
- Registry 在应用启动时校验，在 Run 创建时按 ID/version 解析并冻结执行快照；
- 仅允许 HTTPS 443、精确 ASCII hostname（IDN 使用显式 punycode）、受约束 endpoint，禁止
  userinfo、query、fragment 和重定向；
- 全部 DNS A/AAAA 都必须是原生公网地址；私网、loopback、link-local、metadata、multicast 和
  IPv4-mapped IPv6 均拒绝；
- transport 连接已验证的数值 IP，同时保留原 Host/TLS SNI，并在读取正文前验证实际 peer；
- peer 元数据缺失或不一致时失败关闭；HTTP 认证值只从 Worker 的独立环境变量读取；
- 内部测试使用 MockTarget，不允许通过 HTTP Registry 访问私网目标。

这是应用层纵深防御，不是“完全防 SSRF”证明。生产部署仍需防火墙、NetworkPolicy、安全组或
等价 egress policy，并在 HTTPX/HTTPCore 升级时重跑 peer 合同测试。

## 8. 未完成的安全能力

- 请求速率限制；
- PostgreSQL RLS；
- API Key 权限 scope；
- key 自动轮换；
- 管理员身份与审计 UI；
- malware 扫描；
- artifact 加密；
- 独立的网络出口强制策略与正式 SSRF 渗透测试；
- 正式威胁建模和第三方安全审计。
