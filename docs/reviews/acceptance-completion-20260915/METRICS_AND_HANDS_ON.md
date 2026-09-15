# 新增指标与亲手复现实验

这是可运行系统的监控接线和验收练习，不是生产认证，也不要求新增模型或数据库产品。上一轮原件保留；本轮精确版本与实际测试结果由新的交付回执给出。

## 一、指标到底表示什么

| Prometheus 指标 | 写入位置 | 语义与边界 |
| --- | --- | --- |
| job_lease_authorization_total{operation,outcome} | heartbeat / success / failure 服务 | 成功事务后的 authorized，或实际观测到的拒绝分类；进程重启会重置，不是全局审计账本 |
| job_lease_lock_query_seconds{operation} | heartbeat/result/failure/reaper 取得行锁的查询 | 客户端 monotonic 测得的整个锁查询耗时；包含 SQL、网络、调度和锁等待，不能声称是纯数据库锁等待 |
| job_reaper_expiry_lag_seconds | reaper 成功提交后 | 已回收任务从租约到期到锁后授权时刻的延迟；事务失败不计入，重复扫描不重复计入；不是当前未处理积压年龄 |

operation 只有 heartbeat/result/failure/reaper。outcome 是固定枚举，禁止 tenant/run/job/attempt/worker ID、正文、答案和异常原文作为标签。心跳在已锁定行区分 not_found/state/owner/version/missing_expiry/expired；结果和失败提交保留原SQL前置 fencing，未命中统一记 identity_or_state，不为给出更细标签增加额外查询或猜测到底是哪一个字段。

既有 PlatformMetrics registry 被注入生产 worker/reaper 装配；复用其内部9101/9102端口，不新增暴露端口或存储。API 是另一个进程，不能只抓API就认为抓到了Worker数据。心跳只加载所需授权列，不加载题目正文。开启指标不会更改锁序、重试预算、评分或任务决定。

查询示例（需 Prometheus 正在抓取相关进程）：

```promql
sum by (operation, outcome) (rate(job_lease_authorization_total{outcome!="authorized"}[5m]))
histogram_quantile(0.95, sum by (le, operation) (rate(job_lease_lock_query_seconds_bucket[5m])))
histogram_quantile(0.95, sum by (le) (rate(job_reaper_expiry_lag_seconds_bucket[5m])))
```

没有样本时百分位可为空/NaN，不填成零延迟；必须结合 scrape 的 up 和已有 queue/heartbeat/lease-expired 指标。这里不给未经真实负载校准的告警阈值，也不声称通过长期生产观测。

## 二、随机实验协议

测试：tests/concurrency/test_randomized_lease_lifecycle.py，种子固定0–99，每种场景25轮：有效租约竞争、过期恢复、有效租约取消、过期取消。每轮7或8个并发actor，合计750个初始actor；这是合成数据库操作，不是750个模型请求。

每轮随机排列启动顺序，并从固定0/1/3/7/15毫秒延迟集合取值；真实PG决定最后交错，所以同一seed可复现相同计划但不保证OS调度逐微秒相同。固定屏障回归仍保留，二者互补。

操作包括同一attempt两个成功提交、心跳、失败提交、两个reaper、错误owner及部分场景的取消。竞态结束后有界回收和重新领取，再验证旧执行无法覆盖。断言唯一accepted result、accepted attempt绑定、attempt终止与计数、Run/Job合法终态、成功结果和Outbox一致且只有一条Run完成事件。

每轮记录计划、实际事件顺序、拒绝/异常和DB后置条件。非预期数据库异常、死锁、超时直接失败，不吞掉或自动重试到绿；所有种子保留。100轮通过不等于无死锁证明，不产生吞吐或正式质量A/B结论。

## 三、Windows 严格验收

```powershell
uv run --no-sync python -m scripts.windows_link_gate --junit artifacts/my-windows-links.xml
```

必须在Windows运行且输出路径不存在。实际执行文件symlink防篡改、目录symlink输出/父路径、junction输出/父路径共5项；任一缺失、跳过、失败或重复都使门禁失败。不修改本机管理员权限、开发者模式或策略。GitHub专门的windows-link-safety job以其自身权限真实执行，不能用Linux或门禁解析器的模拟XML单测替代。

## 四、你可以亲自做的三个练习

只使用已迁移的独立测试数据库；不要把下面命令指向生产/个人业务数据库。先安装锁定Python3.12依赖并配置EVALOPS_DATABASE_URL，显式设置EVALOPS_RUN_INTEGRATION=1；每次输出目录都用新名称。数据库夹具会创建并清理其自有测试记录。

```powershell
$env:EVALOPS_RUN_INTEGRATION = '1'
$env:EVALOPS_SCHEDULER_DIAGNOSTIC_DIR = 'artifacts/my-hands-on-new'
uv run --no-sync pytest tests/concurrency/test_lease_authorization.py -k 'heartbeat_metrics' -q -s
uv run --no-sync pytest tests/concurrency/test_randomized_lease_lifecycle.py -q -s
uv run --no-sync pytest tests/unit/product_experiments/test_citation_contract.py -q
```

1. **过期授权**：先预测拿锁之前记时间会怎样，再看heartbeat测试如何持锁、跨过expiry、释放并拒绝；对照新增expired Counter和锁查询耗时。用自己的话解释为何不能用事务开始时间now()。
2. **并发与迟到提交**：打开100seed诊断记录，挑一个有取消或恢复的轮次，按trace还原先后关系。解释为什么多次执行/重试仍只接纳一个结果，为什么不能宣称外部exactly-once。
3. **评分语义**：在引用合同测试中找到source_id/id冲突及多余引用；先预测recall/precision与错误状态，再运行验证。解释来源ID匹配不等于自然语言语义支持，并打开上一轮private/public验证日志区分重算范围。

我可以准备和执行工程实验，但不能替你证明已经掌握。练习尚未由你亲自完成，只影响个人面试准备，不应再作为工程任务拖延或停止的理由。
