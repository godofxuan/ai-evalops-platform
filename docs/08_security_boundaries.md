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

## 6. 未完成的安全能力

- 请求速率限制；
- PostgreSQL RLS；
- API Key 权限 scope；
- key 自动轮换；
- 管理员身份与审计 UI；
- malware 扫描；
- artifact 加密；
- SSRF 防护（HTTP Target 属于后续阶段）；
- 正式威胁建模和第三方安全审计。
