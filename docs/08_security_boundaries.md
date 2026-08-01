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

当前是应用层隔离，不是 PostgreSQL RLS。未来新增 repository 方法时必须有跨 tenant 负面测试。

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

## 6. HTTP Target 出口边界

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

## 7. 未完成的安全能力

- 请求速率限制；
- PostgreSQL RLS；
- API Key 权限 scope；
- key 自动轮换；
- 管理员身份与审计 UI；
- malware 扫描；
- artifact 加密；
- 独立的网络出口强制策略与正式 SSRF 渗透测试；
- 正式威胁建模和第三方安全审计。
