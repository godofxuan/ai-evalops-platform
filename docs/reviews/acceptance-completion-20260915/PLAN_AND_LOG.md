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

## 跨平台随机回归发现的第二处缺陷

- ce7c088本地完整单元1520 passed/3权限skip、集成178 passed/3 MinIO skip，100seed均通过；但其GitHub CI 34945618819失败。Windows/Compose通过，Linux随机seed 2/14/26/30/38/46/54/66/78/86失败，其余90通过。原始CI日志和ZIP已下载并与GitHub摘要核对，不重新运行同一提交来挑绿。
- 十个失败均为live_cancel场景出现两条run_completed。trace显示success-b完成在cancel完成之前；取消路径先做无锁预读，随后SELECT FOR UPDATE虽然读取了新行，SQLAlchemy identity map仍返回已缓存的旧RUNNING状态。它把已成功Run写回CANCELLING，再聚合回SUCCEEDED，从而重复发终态事件。
- 将该时序固化为真实PG屏障：取消的预读已执行后用事务advisory lock暂停，另一真实ResultCommitter提交成功，再释放取消。未修改产品前本机稳定复现两条完成事件（cancel-stale-red），不是只在模型对象上构造。
- 最小修复只为取消路径的锁定查询加入populate_existing=True，强制以拿锁后读到的数据库状态替换本Session缓存。不新增查询、不改变锁序、不删除事件或降低断言。相同屏障测试通过（cancel-stale-green）：只剩一条完成事件、成功结果仍绑定原accepted attempt、没有虚假cancel_requested_at。
- 因代码有新修复，ce7c088及其本地结果不再充当最终版本。下一代码提交必须重新执行完整本地和精确远端CI，全部结果保留到新目录；本轮未以本机通过替代跨平台验收。

## 最终代码冻结与证据交付

- CODE 60773c648923f6cd2118da0e4ebc264644151274在干净detached worktree重新验证：1520单元通过/3本机权限skip；179集成通过/3本机MinIO skip；100seed和50组冷写入均通过；实际固定上游checker37/0skip。全部写入verified-60773c6新目录，之前文件不覆盖。
- 60773c6的Linux CI同一100seed步骤已成功；不会仅凭这一步把整个CI标绿。文档阶段不再改变代码，独立DOC CI与剩余CODE CI可以并行；最终交付必须以两次完整CI成功、下载原始证据校验及远端精确SHA为准。正常推送隔离分支，不自动合并main。
- 新版本直接运行QA/Agent演示、local analyze，以及真实durable报告离线私有重算/公有投影核验。再次确认40计划/39attempt及HTTP调用/24接纳/12失败/4取消，质量状态仍为预设EXECUTION_FAILED。
- 已再次关闭本任务自有PG55435与Redis56385，保留测试数据用于诊断但不打入交付包；不关闭其他进程，不修改Windows策略。原用户工作区保持b122a6d且干净。
- 打包使用原package_audit_closeout的独立派生助手，仅显式指定源码根目录并更新最新阅读入口；原产品脚本不修改。助手、收集与核验脚本随证据提供，仍拒绝dirty源码、代码/DOC差异、数据库运行时及篡改的原始模型包。交付时逐成员复核ZIP，不以“生成了文件”代替完整性检查。
