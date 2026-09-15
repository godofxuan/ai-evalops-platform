# 2026-09-15 独立审核修复执行记录

## 身份与授权

- 用户经总控授权：独立审阅三工作包后本地实现和验证；不推送、合并、部署或改共享简历/教学母版。
- 唯一仓库 AI EvalOps；固定基线 `903ed7ca44e452faa93a62a9515f7fba733a8d1d`。
- 新分支 `codex/audit-remediation-20260915`，独立 worktree；原工作区和旧交付树初检干净。
- 方案全文、总报告、证据索引已读；简历手册读取本项目及共同使用边界。历史探针为 Python 3.13 + SQLite/摘录，不冒称 PostgreSQL 复现。

## 逐项处置（初审，验证后更新）

| 项 | 处置 | 源码/材料依据及调整 |
| --- | --- | --- |
| C-P0-1 heartbeat/commit 锁前取时 | 接受，先真实 PG 复现 | heartbeat.py/results.py 在 await 前取应用 now；fencing 谓词本身仍保留 |
| C-P0-1 reaper 反向锁序 | 接受，先固定排程复现 | reaper.py 先锁 Job，aggregation.py 再锁 Run |
| C-P0-1 相邻 failure 路径 | 扩展同类复核 | failures.py 同样 Job→Run 且锁前时间；不可只修 reaper |
| 全局锁序机械套用 | 调整 | experiment_admission.py 在持 Job 时仅用 SKIP LOCKED 取得 parent/Run；需区分非阻塞尝试与真正等待，保留公平性/并发控制 |
| C-P0-2 引用别名冲突 | 接受，先导入实际模块复现 | 统一新契约，但旧版评分必须保留，不能重写历史报告 |
| C-P1-3 CI 缺上游 skip | 接受 | 原 CI 的成功不覆盖跳过的真实 BFCL checker；新 release gate 缺料须失败 |
| C-P1-3 Cross Family 缺包 | 本机可解除 | 原 ZIP 与 receipt 存在；按原指纹重新验证，不生成同名替代包 |
| C-P1-3 20×2 合成故障演示 | 接受，复用实际持久路径 | 与旧 632 次模型调用严格分开；预冻结异常与分母 |
| 新增模型/基础设施/新质量实验 | 拒绝本轮扩张 | 三包只修可靠性、评分合同和发行证据；不改 gold、阈值或旧响应 |
| 本人亲自掌握/独立设计 | 外部待用户实践 | 自动化实现不能证明用户已掌握；只准备教学练习与代码入口 |

## 环境与步骤

1. 检查原 repo 与 `codex/public-benchmark-validation-v1` 都干净，从精确 SHA 创建新 worktree，保留旧资料。
2. 按 diagnose/TDD：先构建可复现反馈循环，再按每个行为红→绿，数据库后置条件按任务书要求保留，不以纯函数替身冒充并发证明。
3. 本机没有可用 Docker/PostgreSQL 服务或 WSL 发行版。经 PostgreSQL 官网推荐 EDB 下载页定位便携 PostgreSQL 18.6；只在本轮 artifacts/runtime 解压。旧 CI 使用18.4，此环境差异明确记录，不声称同镜像复现。准备仅绑定 loopback 的独立空测试库，不安装 Windows 服务。

## 外部依据

- PostgreSQL Windows 下载页（2026-09-15读取）：https://www.postgresql.org/download/windows/
- EDB 便携包链接：https://get.enterprisedb.com/postgresql/postgresql-18.6-3-windows-x64-binaries.zip
- 权威时钟语义：https://www.postgresql.org/docs/18/functions-datetime.html （`clock_timestamp`为调用时刻，`CURRENT_TIMESTAMP`为事务开始时刻）

## 未完成与回退

初始阶段尚未应用业务修复；以下按时间追加真实进展，不把初始状态当最终结论。回退范围为本轮新分支与新测试库，禁止覆盖旧数据或旧报告。保留旧只读交付入口，不部署有风险的旧实现。

## 环境问题与首条反例

- 便携包 SHA-256 `59f8ce701c63c2ed623c665a5e51b3ef6f2e37ccf837b68ffeed0742d0ae6abd`，版本18.6；摘要用于本次关联，不冒充发布者独立签名。
- 首次 `Start-Process -Wait` 等待整个后代进程树（包含数据库），createdb 未执行。过早测试为 database does not exist（red-heartbeat.log/xml），只算环境错误。
- 中止启动器后仅重启本轮PG，改成 `-PassThru` + pg_ctl本身 `WaitForExit(20000)`；loopback55435、evalops_audit_20260915，迁移0001至0033完成（migrations.log）。
- 进一步进程检查发现其他任务在Z:/.tools/pgsql使用PG，不接触其库。初始PATH探测不等于整机不存在PG；本轮继续自己的隔离实例。
- 原版真实PG反例：red-heartbeat-pg.xml/log 为1 failed，DID NOT RAISE LeaseLostError。先观察pg_stat_activity确有锁等待，再以服务器clock_timestamp越过expiry作为释放条件，旧心跳仍成功。锁快照保留在lease-diagnostics。
- 假设排序：锁前应用时间陈旧；事务时间函数语义不合适；身份谓词缺失。源码身份谓词仍在。最小改动是Job NO KEY UPDATE锁后读DB时间，再原owner/version/status/expiry条件更新。显式测试Clock仅保留确定性接缝，生产装配不注入。
- 首次补丁调用被工具沙箱拒绝；备用CLI路径因应用更新不存在，因此green-heartbeat.xml实际仍为旧代码1 failed/4 passed，不误记为修复通过。重新定位当前补丁执行器后才应用改动。

## C-P0-1 实现与回归

- heartbeat 获得 Job NO KEY UPDATE 后读取 clock_timestamp；success/failure 在 Tenant→Run NO KEY UPDATE→Job→Attempt 后重新核验 owner/version/status/expiry。线性化授权时刻有效，不承诺整个事务永不越过未来 expiry。
- success 与 failure 各在 Run/Job/Attempt 锁上等待跨过 expiry，旧路径各3失败；修复后7个真实授权测试通过。
- reaper 原 Job→Run 与提交 Run→Job 在真实PG固定屏障下产生 DeadlockDetected（red-reaper-lock-order-v3）；这次复现时提交的时钟补丁已应用，reaper尚为原版，不冒称全树原封不动基线。
- 初始两次锁观察失败是 pg_stat_activity 事务缓存快照；观察连接增加 pg_stat_clear_snapshot 后捕获真实环，旧失败日志保留。
- reaper 改为有限身份发现→排序Tenant→排序Run NO KEY UPDATE SKIP LOCKED→排序Job SKIP LOCKED→Attempt→重新取时检查。保持单个有界批次事务，limit最大1000，候选发现不是回收授权。
- Run聚合只改非键字段，采用NO KEY UPDATE，避免持Job再升级强锁。
- 原旧测试替身没有父级查询结果，导致3个失败；补齐假数据库查询队列，未删业务/outbox断言。
- p0-full-concurrency.xml/log：114 passed，155.20秒，包含既有公平性、租户并行、持久公平轮、Job claim与新增8项实际PG回归；有限测试不构成全局无死锁数学证明，不宣传吞吐提升。

## C-P0-2 逐步接线

- 实际模块导入反例4 failed（red-citation），未使用报告中的函数摘录替代。
- 发现关键区别：score_product_case 旧完整路径用诊断recall覆盖注册分；不能把注册函数错误直接包装成所有完整执行都质量误放行。
- 新唯一解析入口对冲突/非字符串/空白ID报 target_citation_invalid；缺少两键是unresolved，计入precision分母；别名相同接受；不自动str/trim选有利结果；重复相同ID去重。
- 首次green-citation-core仍4失败：异常已拒绝但测试错误地匹配人类消息而非code属性；修正为检查.code，控制组12 passed。
- 新执行版本：local result3/input snapshot2；worker product-v3/observation3；aggregation3。明确保留product-v2注册和旧评分规则，未知/混合版本拒绝；不改旧报告原件、gold或摘要。
- 第一轮跨路径单测425项：423 passed/2 failed，仅新增v3后旧注册名单/准备器版本断言尚未更新；补齐明确的版本预期，不放宽其他断言。完整持久路径与历史原件复核仍待后续证据。

## 验证运行时与资源边界

- 用户再次要求完成升级、实验和整体验证。总控提示RAG在独立GPU实验，本轮不做新增模型调用，只做合成HTTP/DB和旧响应离线checker。
- Redis便携第三方Windows移植8.8.1，与CI主版本一致但不是官方Linux镜像等价验证；只监听127.0.0.1:56385，不装服务，不使用私有数据。
- 发布页 https://github.com/redis-windows/redis-windows/releases/tag/8.8.1 ，下载资产摘要与API/发布正文一致：1a0741a8f997a50ad7a32370e9ddf719ed3d5d87701324c57b7b34518b980460，13616234字节。Redis PONG已确认。
- BFCL缓存从旧交付复制到本轮新目录，prepare_pilot逐文件校验固定SHA与许可证，100题原摘要e95152…保持不变；复制/重新准备不计模型调用。

## 补充锁序发现与完整集成问题

- 初次 claim/cancel 反例因先前失败留下可领取Job而取错任务，是夹具污染。改用全新库后，QUEUED和RUNNING普通Run都复现实际 DeadlockDetected；后者来自 transactional outbox 的隐式FK KEY SHARE。普通Run新增SKIP LOCKED父级保护，RUNNING只需KEY SHARE，保留并行能力。
- reaper/commit 固定屏障改为20次参数化重复。补充合法心跳等待长于renewal、不同owner/version、expiry等号4项真实DB控制；等号专门注入Clock，其他时刻用实际数据库时间。
- p0-expanded-concurrency 的2失败是已有OneRowSession没有scalar父级读取接口；补齐替身，不削弱断言。最终数字不把这些中间计数相加。
- product-durable-v3 首次强杀测试失败：Windows默认Proactor不支持Psycopg。复用项目Selector事件循环入口后，完整持久主场景通过（product-durable-v3-selector）。
- full-integration-final：65 passed / 2 failed / 3 skipped，两个失败是同类Windows Selector不支持asyncio子进程。遥测启动改为线程内Popen、异步等待/有界kill，子进程复用Psycopg兼容入口。37项遥测+租约控制通过（telemetry-lease-controls）。
- full-integration-v2：70 passed / 1 failed / 3 skipped。失败是matrix恢复夹具在retry未到时持其他题目屏障调用claimer，触发其合法blocking fallback，等到自己的屏障。未延长预算：改为查询服务器next_attempt_at已就绪后才领取，生产scheduler不变。matrix-readiness复核1 passed，40/24/12/4/39计数不变。失败不是模型质量结果，原日志保留。
- HTTP超时的ConnectionAbortedError来自测试服务器向已关闭连接写回；仅测试夹具忽略这个预期断连类型，不改变目标错误分类或生产网络校验。

## 评分版本、报告与历史原件

- 新 local manifest/result3、input snapshot2；durable product-v3 / observation3 / aggregation3。旧v2显式注册和旧HTML保留；legacy HTML固定摘要437d008017b4f34049751e57571b417cd027de9efa05dd2a1a8f15f7b8f4f705。
- 新报告首屏回答任务、质量、证据、成本延迟四问；只有v3增加面板。95项版本/报告控制通过。local完整120题回归保留239观察+1非法输入失败；错误仍在240计划执行分母。
- 新QA/Agent真实worker观察故障覆盖长答案、引用冲突/数值/空白，以及Agent终态矛盾；每个4Job保留3接纳1失败，private完整重算，并验证伪改DEMO_PASS后重新hash仍被拒。
- 从原CrossFamily ZIP的source生成120题旧local v2报告，再由当前load_evidence重算，得到LOCAL_RECOMPUTED_NOT_PROVENANCE。没有改旧报告、gold或历史hash。
- 原包SHA256 3db9535f56a1ff9d3e0539664edb260aa542e3d7d98aeffd8eec8b316300e170，14666成员全部校验。首次长目录解压触发Windows路径长度错误；保留失败目录，换全新短路径eo-r0915成功。原源码下BFCL/RAGBench四模型比较重算退出码均0；Python审计钩子拒绝网络和新子进程，不冒充OS沙箱或全新依赖安装。
- 原始632模型调用仅是历史值。本轮调用模型0。matrix本地HTTP请求都是synthetic，不并入benchmark分母。

## 构建上下文与专属依赖

- full-unit-final：1510 passed / 1 failed / 3 skipped / 70 deselected。初步观察是构建指纹前后变化；进一步隔离确认.dockerignore漏掉artifacts，最小fixture新增raw.json使构建文件数19→20。故不只是“测试时写文件”：私有运行证据不应作为构建输入。
- red-build-context为真实1 failed。新增artifacts排除规则；真实app代码变化仍改变指纹。green-build-context 30 passed。未实际构建Docker镜像，不能声称镜像安全验收。
- 原依赖环境中typing_extensions/_virtualenv/pygments文件在后续运行时突然缺失；原因尚未确认。full-unit-v2与full-integration-v3的运行已中止，日志只作环境故障，不作完整验收。
- 不改旧环境。在本轮.venv以Python3.12.13、uv.lock --locked --all-groups重新安装141个锁定包；依赖锁未改动。新的完整验收统一使用本轮专属环境，见isolated-dependency-sync.log。
- 向总控发送包含详细环境路径的进展消息被自动审查拒绝，原因是未先验证目的任务归属；该消息未发送。随后只读确认它确为用户的三项目审核总控；最终同步只发送必要项目结果与用户要求的交付路径，仍以实际发送结果为准。

## 发布门禁与边界

- 初始release flag被忽略时11 passed/16 skipped仍exit0；新增required_bfcl_root后缺料产生显式失败。CI fast单测允许optional，但独立release gate要求固定BFCL上游、许可、case摘要齐备，真实checker全部运行且零skip。
- release-isolated：37 passed、0 skipped，cache key含上游完整SHA和SOURCE_HASHES清单摘要。本机跑过真实checker不等于真实模型推理。
- MinIO官方Windowsarchive返回410；本机无Docker/podman/可用Go运行时。未临时换不可信镜像，3项MinIO用例明确skip；Linux Compose、MinIO及新分支GitHub CI待外部条件/授权，不借用903ed的历史CI。
- 用户的学习掌握不能自动判定通过；完整简历、答辩和亲自复现练习已写入RESUME_AND_DEFENSE.md。历史NEGATIVE_SCALING、正式A/B、人评及生产限制保留。

## 精确提交与文档收口

- README更新后旧清单报evidence size drift。没有改旧清单hash：复制旧c5dbeec README原件并依其source_sha校验，当前README交给新CODE/交付身份。2项真实完整清单与缺失/篡改反向测试通过；CLI明确不把旧manifest说成覆盖当前README。
- 由于便携数据库、缓存和.venv造成目录扫描很重，并在旧清单问题修正前开始采样，full-unit-isolated被明确中止；不是完整通过。将代码候选提交为bd10966fdc3a7abc094f8cf2b805cec84799f070，再创建完整干净detached源树验收。
- CODE完整集成code-integration-final：71 passed、3 MinIO skipped、273.73秒。matrix-code绑定实际CODE_SHA，40/24/12/4/39的冻结计数与private/public离线范围均确认。
- CODE完整单测code-unit-final：1512 passed、1 failed、3权限skipped、74 deselected，428.26秒。唯一失败是README所指CLOSEOUT_RESULTS.md尚未落盘。本次DOC补齐实际收口与同步材料，随后再执行DOC全套，最终结果由doc-unit-final与交付回执记录；不删除CODE红日志。
- 原工作树与903ed基线工作树再次git status均为空；新远端分支只读ls-remote结果为空，没有推送、合并或触碰main。
