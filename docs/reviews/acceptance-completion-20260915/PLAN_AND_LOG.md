# 遗漏验收项补齐：计划与执行记录

起点：12b6ca495b03fd9fb67a3f987ee51c5b37ada0ac，沿用隔离分支 codex/audit-remediation-20260915。main、原工作区、RAG、旧证据包保持不变。

用户要求完成原安排；上一轮把主要修复完成当作任务书全部完成，遗漏了以下可执行验收。本轮只补它们，不增加模型或基础设施。

## 预设范围与验收

1. 利用现有进程级 Prometheus registry 新增有界指标：租约授权结果/拒绝原因、锁查询耗时、已提交回收任务的到期延迟。锁查询耗时包含 SQL/网络/调度和锁等待，不冒充纯 PostgreSQL server lock-wait。指标不得反向决定领域状态，不引入 ID、题目、答案、凭据标签。
2. 真实 PostgreSQL 冻结 100 个随机种子，覆盖成功/失败提交、重复提交、心跳、取消、双 reaper、过期后恢复与旧结果迟到；每轮保留操作顺序、异常、状态、唯一接纳与 attempt/outbox 后置条件。不丢弃失败或挑好种子；有限压力测试不是数学证明，不宣称吞吐提升。
3. 添加专门的 Windows CI，真实验证文件/目录 symlink 与 junction 防护。缺权限必须失败而非以 skip 通过；不修改用户主机的系统权限。
4. CI 的合成报告显式使用当前提交 SHA，避免上一轮测试占位身份被误读。此为现有证据链修补，不改历史报告。
5. 提供用户可亲手执行的三个练习入口；不把用户个人掌握程度记为工程验收失败，也不代称用户已掌握。

顺序：真实 heartbeat 指标红→绿；结果/失败/reaper 指标与回滚控制；100种子真实并发；Windows严格门禁；锁定环境全套回归；正常推送本隔离分支并核对精确CI；保存原始证据与最终交付增补。无公开API请求格式变更，只新增监控序列及测试入口。

## 执行记录

- 已核对任务书第1.3.7项：最小 telemetry 是明确要求，不是等待生产部署的前置条件。现有 registry 已具备 Counter/Histogram，不需要新数据库。
- 已核对 Windows 原始JUnit：3项因创建符号链接权限不足跳过；Linux只能证明其平台行为，需增加Windows门禁。
- 使用测试先行流程；真实PG测试采用独立数据库和有界超时，结果文件写新目录，保留旧轮次所有证据。
- 首次PG启动遗漏旧轮次的显式端口参数，在本任务自有cluster的loopback5432启动；确认进程/数据目录归属后关闭并以55435重启，没有操作其他PG实例。首次尝试默认postgres角色失败，随后确认原cluster角色evalops，创建新的evalops_acceptance_20260915并迁移到0033。此为环境准备错误，不算产品反例。
- heartbeat指标先因接口缺失失败；实现后真实跨expiry锁等待、续约和身份控制6项通过。随后扩展到success/failure/reaper；一次测试错误传入TargetTimeoutError参数，修正夹具并保留失败日志。同步完善后台测试任务异常回收，避免早期异常只表现为等待超时。
- 指标绿阶段：真实锁等待及事务回滚5项通过；完整租约回归38项通过；相关单元回归93项通过。锁查询计时不新增SQL；heartbeat只加载授权列，避免监控读取题目正文。
- 随机协议首次完整执行100/100通过（50.48秒），诊断在random-first目录保留；尚未有最终提交时明确标UNBOUND_LOCAL_WORKTREE，不冒充绑定代码身份。最终CODE确定后须重跑并绑定该SHA。
- Windows本机严格门禁实际2 passed/3 skipped并以非零退出，证明缺权限不能变成验收成功。专门Windows CI已接线，尚未运行前不得标通过。
- 新测试复用真实PG fixture时，mypy发现同一文件的短模块名/完整包名重复；为tests及concurrency增加包标识，修复后mypy259文件通过。ruff/format通过；不修改类型检查门槛。

## 全套回归发现并修复的新问题

- 初始补齐提交6a9360c8d745066bed09b301344b80667ae8c223：完整单元1520 passed/3 Windows权限skip；集成175 passed/1 failed/3本机MinIO skip。100随机种子全部通过，但真实双版本实验的8路幂等创建触发了artifact_blobs.storage_path唯一约束异常，不能据此宣布全绿。
- 原始日志中的SHA、长度与路径和数据库已有行完全相同，排除了内容路径不一致。另建独立PG数据库；新增50组×8路冷内容登记回归在第2组复现IntegrityError；不同SHA抢占同一路径的负控也未得到预期领域错误。两项red保留在cold-blob-red-2。第一次red尝试使用前一个失败后残留任务的DB，夹具领取到错误任务，只算环境隔离失败，不算产品反例。
- 最小修复：INSERT的DO NOTHING不再仅指定SHA唯一键，覆盖该表所有唯一冲突；然后仍锁定SHA对应行，严格核对生命周期、长度、路径。不同SHA碰撞同一路径时明确抛ArtifactMetadataIntegrityError，不吞掉损坏数据。不增加迁移、不删除唯一约束、不增加业务重试。[PostgreSQL INSERT文档](https://www.postgresql.org/docs/current/sql-insert.html)说明省略DO NOTHING conflict target覆盖所有可用唯一约束；实际并发回归另行验证行为。
- 首次green组合中artifact三项通过，但完整pair测试因本次命令遗漏Redis环境变量失败，保留cold-blob-green。补环境后完整pair实际通过（包含执行、导出、私有重算），旧artifact清理测试却暴露跨次运行残留DELETED tombstone；修正测试数据按本次tenant唯一化，并清理其所有自有且无人引用的blob，生产生命周期拒绝行为不变。cold-blob-green-2保留该失败，最终CODE要在全新DB完整重跑。
