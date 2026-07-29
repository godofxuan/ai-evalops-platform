# 面试问题与回答要点

## 架构与可靠性

### 1. 为什么不用 Celery？

项目的学习目标是显式实现 PostgreSQL 事务、`SKIP LOCKED`、lease、heartbeat、
fencing、retry 和 Reaper。Celery 会把最需要展示的机制隐藏在框架内部。真实业务
若不需要学习这些机制，应重新评估自研成本。

### 2. 这是 exactly-once 吗？

不是。Worker 可能执行同一 Job 多次；系统依靠 lease fencing 和 CaseResult 唯一
约束阻止陈旧 Worker 提交第二个最终结果。准确语义是 at-least-once execution 加
idempotent result persistence。

### 3. Redis 丢失为什么不丢结果？

Job/Attempt/CaseResult/Run 都在同一个 PostgreSQL 正确性路径中提交。Redis 发布发生
在提交后，仅用于短期通知。SSE 重连先读 PostgreSQL snapshot，再订阅 Redis。

### 4. Worker 崩溃怎样恢复？

heartbeat 停止后 lease_expires_at 变为过去。Reaper 用 `FOR UPDATE ... SKIP LOCKED`
锁住过期 Job，结束旧 Attempt，再依据 retry/cancel/max_attempts 转换状态。新 Worker
只能在重新 claim 后获得新的 owner/version。

### 5. 为什么结果提交还要检查 version？

只检查 owner 不能防止同名 Worker 重启或旧协程晚到。owner + version + live expiry
共同形成 fencing token；每次 heartbeat 更新 version，结果必须使用最新 version。

### 6. Reaper 自己并发怎么办？

多个 Reaper 使用相同的 `SKIP LOCKED` 扫描和短事务。一行在同一时刻只被一个 Reaper
锁定；集成合同用两个 Reaper 同时回收并验证 job ID 无重复。

## 幂等与事务

### 7. Idempotency-Key 为什么还需要 request hash？

同一个 key 可能被误用于不同 payload。canonical hash 相同则重放已有 Run，不同则
返回 409。数据库 `(tenant_id, idempotency_key)` 唯一约束处理并发竞态。

### 8. 为什么不能“先查不存在，再插入”就结束？

两个事务可能同时查到不存在。正确性最终依赖数据库唯一约束；冲突事务回滚后读取
胜者并再次比较 request hash。

### 9. API 响应丢了怎么办？

数据库提交与客户端收到响应不是同一件事。客户端用相同 Idempotency-Key 和 payload
重试，服务返回已提交 Run，而不是创建第二组 Jobs。

### 10. 为什么 artifact 文件写入不放在长数据库事务里？

大文件 IO 会延长锁持有时间。先做有界校验和原子 content-addressed publish，再用
短事务写 metadata。代价是跨文件系统/数据库不是一个原子事务，需要 orphan GC。

## 多租户与安全

### 11. tenant_id 从哪里来？

API Key 查库后生成 Principal；请求体不接受 tenant_id。每个资源查询同时使用资源
ID 与 Principal.tenant_id。

### 12. 为什么跨租户和不存在都返回 404？

避免用不同状态码枚举其他 tenant 的资源 ID。授权不是 cursor 或 UUID 的属性，仍由
每次 tenant-scoped SQL 决定。

### 13. API Key 为什么只存 hash？

数据库泄露时不直接暴露可用凭证。明文只在创建成功后显示一次；认证使用版本化
scrypt hash 和常量时间比较，并对未知 prefix 做 dummy hash 降低时序差异。

### 14. HTTP Target 的 SSRF 防护完整吗？

不完整。代码限制 HTTPS、host allowlist 并检查 DNS 地址，但 DNS check 与实际 connect
之间仍有 TOCTOU。生产环境还需要网络 egress policy、固定 resolver/proxy 和审计。

## 指标与可观测性

### 15. 为什么 run_id 不作为 Prometheus label？

它是无界高基数，会为每个 Run 创建 time series。ID 进入 trace/log；Prometheus 只保留
method/route/status 这类有界维度。

### 16. Counter 与数据库事实不一致怎么办？

Worker counter 是进程视角，重启会归零，多副本需要 sum；Run/Job 当前事实仍查数据库。
queue/running/heartbeat Gauge 在 API scrape 时直接从 PostgreSQL 刷新。

### 17. OTLP endpoint 不配置时 trace 有什么价值？

SDK 仍生成 trace ID，可关联本进程日志和单元测试，但 span 不会持久化到后端。不能
声称已经具备生产 trace 查询能力。

### 18. 为什么 API 和 Worker 不是同一个 trace？

异步边界没有持久化 W3C parent context。当前用 run/job/attempt attributes 关联不同
process trace。下一步可在 Job 保存 traceparent，并让 Worker 创建 child 或 Span Link。

### 19. SSE connection Gauge 为什么容易泄漏？

StreamingResponse 使用异步生成器。若外层包装器不显式关闭内层 generator，Redis
subscription 和 Gauge 都可能泄漏。本阶段回归测试正好发现并修复了两次关闭传播问题。

### 20. 4xx 的 outcome 应该算 error 吗？

当前日志的 outcome 表示服务端执行是否出现 5xx/unhandled error，4xx 是已处理请求；
Prometheus status 标签保留精确状态。若告警语义需要 client_error，应增加独立分类，
不要悄悄改变既有字段。

## 评测语义

### 21. lexical exact match 能叫“语义正确率”吗？

不能。它只比较规范化文本，适合 deterministic regression，不证明事实正确、完整性
或引用质量。自动指标和人工评审必须分开命名和存储。

### 22. p95 怎么定义？

项目使用 type-7 线性插值：在排序数组的 `(n-1)*q` 位置做相邻插值。必须写明算法，
否则不同库和小样本可能给出不同值。

### 23. 为什么 bool 不进入 numeric metric？

Python 中 bool 是 int 子类，直接 `isinstance(value, (int,float))` 会把 true 当 1。
系统显式排除 bool 和 NaN/Infinity，防止分布统计污染。

### 24. 不同 Dataset Version 为什么只比较 case_id 交集？

差集没有两侧结果，不能计算同一 case 的 delta。响应明确 warning、交集与左右差集
数量，避免把不同样本集合的聚合差异伪装成模型改进。

## 人工评审

### 25. can_review 能证明是真人吗？

不能。它只表示管理员向该凭证授予 reviewer 权限。自然人身份、培训、反自动化和利益
冲突控制属于更高层治理。

### 26. 为什么两位 reviewer 还需要 Task 行锁？

`(task_id, reviewer_id)` 唯一约束只防同一 reviewer 重复提交，不能原子限制“最多两个
不同 reviewer”。锁住 Task 后再计数和写入，才能串行化这个业务不变量。

### 27. 盲评如何防止看到机器分数？

候选 SQL 不选择 metrics_json，reviewer 查询只 join 自己的 submission，artifact
serializer 也只接受盲化 packet。三层边界减少未来重构误泄露。

### 28. Cohen’s kappa 什么时候返回 null？

当 expected agreement 为 1 时分母为零，kappa 不定义。返回 null 比伪造 0 或 1 更
诚实。

## 实验与证据

### 29. 231 passed 能证明性能好吗？

不能。它证明纯逻辑/API 合同没有回归。真实 PostgreSQL/Redis 测试在本机 skipped，
500-case 扩容实验因 Docker 缺失未执行。

### 30. 如何判断扩容有效？

固定数据、Target delay 和机器环境，比较 1/2/4/8 Worker 的 wall time、throughput、
p50/p95、retry/failure/duplicate 和 DB lock wait。只看平均值或最好一次不够。

### 31. 为什么结果文件拒绝覆盖？

负面结果也是证据。覆盖会形成幸存者偏差；每次实验应使用新路径并保留配置、时间和
Run ID。

### 32. 当前最值得继续做什么？

在有 Docker 的环境运行真实合同和四组扩容实验；保存 PostgreSQL lock wait、资源利用
和所有失败结果；随后再决定索引、batch claim、连接池或 Worker 数，而不是先猜优化。
