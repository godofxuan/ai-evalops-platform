# 可信评测产品执行记录

## 2026-09-07 第十六检查点：真实网络与 worker 强杀恢复（CI 待验证）

第十五检查点 `a10c785f5e88d9c53c3348d037b3e78cf88c2c47` 的 [CI 34112208092](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34112208092) 已 completed/success，包含 SDK→真实 API/数据库→不可变报告下载→原始数据独立重算与跨租户拒绝。

- 先核对 S5 缺口：上一检查点客户端真实 HTTP 不等于目标服务真实 HTTP；MockTransport 的 worker 集成也不等于进程死亡恢复。因此新增仅 tests 下的网络/进程夹具，生产 HTTP 目标、SSRF 策略、worker、调度器、租约和 reaper 代码均不改。
- 真实网络夹具：ThreadingHTTPServer 仅绑定 127.0.0.1 动态端口，AsyncHTTPTransport 真正通过 TCP 收发。仅注入测试 transport 将固定公共 fixture IP 的 /query 请求映射到该端口，并先检查真实物理 peer 为本机端口，再提供模拟公共 peer 元数据；DNS 身份也明确是夹具。该证据不证明真实公网 TLS/DNS/peer 认证，不能抹掉这个限制。
- 网络 RED/GREEN：初始缺少 fixture 模块导致收集失败；实现后发现测试配置遗漏必填 target_id，严格构造器正确拒绝。核对实际配置模型，补测试字段而不放宽生产策略；随后真实目标 HTTP 1 passed（0.73s），断言 Agent 终态/工具/费用与实际 job/attempt 头保留、gold 不外发、显式 public_context 仍转发。
- 真实进程场景：每个场景从公开鉴权 API 创建双组实验，先用既有 worker 完成一题；spawn 独立 worker，分别在 committed claim 后/执行前，以及真实 HTTP 完成后/结果提交前，通过本进程 Pipe 屏障通知父测试。父测试只 kill 自己创建的精确子进程，不杀未知 PID，不把协程取消冒充 OS 进程死亡。
- 恢复断言：实际 1 秒租约、0.2 秒心跳；杀进程后按真实到期状态轮询现有 reaper，使用 0.01 秒固定退避，不改数据库时间、不伪造租约。恢复其余三题，原已完成题不能再被调用。claim 前执行屏障应总计 4 个服务请求；HTTP 完成后屏障应总计 5 次（同 Job attempt 1/2 各一次），明确暴露外部重复副作用风险，不宣称 exactly-once。
- 结果断言：重放死亡 worker 的旧 claim 写入 stale poison 必须 LeaseLostError；最终报告恰有 4 个不同 result，恢复 Job 只绑定新 accepted attempt 2，其余为 attempt 1。服务关闭后仍可公开 API 导出同一私有报告并用原始数据重算；两题仍 INSUFFICIENT_EVIDENCE，不伪造质量 PASS。
- 本地检查：72 passed、1 PostgreSQL skip（2.31s），覆盖实际网络及原目标安全回归；全仓 lint、636 文件 format check、CI 同款 mypy 223 源文件通过。真实进程+数据库场景仅确认可收集，仍须本检查点自己的 CI。直接同时把 tests 辅助文件和集成入口传给 mypy 曾造成相同模块双路径错误，改回现有 CI 的 app/scripts/tests/integration/tests/concurrency 入口通过；未修改包结构或屏蔽错误。
- 文档修正：按 Settings 实际字段把新指南错误的 EVALOPS_PRODUCT_EXPERIMENT_CODE_SHA 改为 EVALOPS_PRODUCT_EXECUTION_CODE_SHA。该错误在后续代码核对中发现，不是已观察到的部署失败。下次发布须包含更正，避免照文档启动失败。


## 2026-09-07 第十五检查点进行中：可恢复客户端与命令行

第十四检查点 `d3a1e573c0fd40d85515915f29a2243cda6bc8d6` 的 [CI 34108307000](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34108307000) 已 completed/success。该结果覆盖上一节新增的真实数据库集成，不代表本节未提交代码已有远端 CI。

- 修改原因：仅有 API 不能方便地让用户退出后继续操作。新增 ProductAPIClient 及 `python -m scripts.product_experiment_client`，先实现 get/cancel/wait，固定使用服务端实验 UUID；不是另建实验或另建调度器。
- 网络边界：HTTPS 默认；明文 HTTP 仅接受 localhost/127.0.0.1/::1，拒绝凭据、查询串、fragment 和路径基址。自有 HTTP 客户端关闭环境代理继承；所有请求显式禁止重定向，即使注入的客户端默认开启重定向也不跟随。Authorization 使用 Bearer，与实际服务端合同一致。客户端注入仅用于外部网络边界测试。
- 资源和隐私：单次请求总时间上限包含正文读取，响应逐块限制，拒绝压缩响应，复用严格 JSON 深度/重复键/非有限数校验，再验证类型及实验 ID。错误仅输出固定安全码，不回显服务器正文、URL 或令牌。CLI 从指定环境变量取令牌，不接受令牌参数。
- 等待语义：READY_FOR_ASSESSMENT 只是执行完成可评估，不等于质量 PASS。wait 超时返回退出码 4 和原实验 ID；Ctrl+C 返回 130，均不发送取消操作。get/cancel/wait 成功返回 0 只表示操作成功，不能替代质量门禁退出码。提交及报告下载仍待后续接入。
- TDD 过程：首次客户端模块不存在，测试收集失败；最小实现后 5 项通过。取消操作反例失败于缺少方法；同轮正常查询反例另发现测试把 Run 小写 queued 错写成实验层大写 QUEUED，核对实际枚举后只修测试。新增 wait 先明确失败于缺少方法，再实现。最后等待超时测试确认网络只出现 GET。
- CLI 验证：缺令牌测试先失败于入口不存在，实现后安全退出 2。另以独立 Python 子进程连接真实本机 ThreadingHTTPServer，验证 get/cancel/wait 的方法、路径、鉴权与输出不含令牌；三项真实 socket 测试通过。这里不是 worker 进程崩溃恢复测试，不替代 S5。
- 验证记录：中间产品实验模块 163 passed（10.17s）；之后客户端定向 11 passed（0.83s），CLI 4 passed（6.24s），存在重叠，不相加。新增客户端和 CLI mypy 通过。初次 lint 发现长行及嵌套 context manager，格式化并合并后定向 lint 通过。后续扩大回归和本检查点精确 CI 仍待执行。
- 路径核对问题：一次尝试 `tests/product_experiments` 不存在，改由 rg --files 定位实际 `tests/unit/product_experiments`；没有因此修改目录结构。

本检查点后续进展：

- submit/export 已接入 SDK 与 CLI；提交响应模型移到共享 service 合同，API 类名与字段保持兼容，禁止额外响应字段。原始数据 SHA、控制请求 1 MiB/原始数据 10 MiB/提交 envelope 16 MiB 在请求前检查；同键重放保留精确原始字节。缺方法反例先失败，实现后提交/API 回归 37 passed。CLI 超限文件反例先失败于没有 submit 命令，再实现限量读取；不是先全部 read_bytes 后比较大小。
- 离线验证器区分 PUBLIC_PROJECTION_ONLY / PRIVATE_SOURCE_REQUIRED / PRIVATE_RECOMPUTED。校验报告字节 pin、内部内容 hash、结果快照 hash 和实验身份；有原始输入时重新运行 shared aggregation 并比较完整规范化内容。修改质量状态再重签报告 hash 仍被拒绝。QA/Agent、缺原始材料和公共边界共 4 项定向通过。重算自洽不等于来源认证，报告中的 CLIENT_DECLARED 仍不升级为独立认证。
- 新 evalops.durable-bundle/1.0 与旧 local manifest 明确分开：固定 report.json/report.html/manifest.json，私有包必须再有 dataset.json；不允许偷偷缺源变成完整私有包。不覆盖现有目录，使用本次专有临时目录和排他锁，验证后 rename；拒绝符号链接/junction、未知文件、文件 hash/大小不符，并重生成 HTML 比对。不清理其他 writer 锁；进程强杀残锁仍待 S5 专门验收。
- CLI 新增 export 和无需 API/令牌的 verify。真实本机 HTTP + 子进程下载私有报告，离线重算成功但两题样本的质量仍为 INSUFFICIENT_EVIDENCE，export 正确返回 2；verify 返回 0 仅表示完整性。该新增路径及原操作共 8 passed（11.01s）。异步测试中直接 subprocess.run 触发 lint，改为 asyncio.to_thread，不阻塞测试事件循环。
- 真实数据库集成追加 SDK 按 ID wait/public/private export、跨租户 404、精确私有 report SHA 与原始数据独立重算，确认目标请求数未增加。该新增断言仍待本检查点自己的 CI；未因第十四检查点 CI 已绿而提前写通过。
- 扩大回归 232 passed、2 skipped（66.77s）：Windows 不允许创建 symlink 的旧 local 测试明确 skip，隔离 PostgreSQL 本地不可用明确 skip。631 文件格式检查、全仓 lint、223 源文件 mypy 通过；后续又追加 HTML+manifest 同时篡改的重签拒绝断言，提交前需再运行定向验证。各轮结果有重叠，不能相加。
- 新操作指南 docs/durable-experiment-client.md 说明真实前置条件、两种 dataset SHA、环境变量鉴权、恢复、可见性、退出码、预算和外部 hash 锚点；原迁移文档旧阶段文字保留但标明不是当前功能状态。没有新增原始数据下载接口：私有完整包使用操作者原有原始输入，避免扩大敏感数据读取面。
- 第十四检查点已向简历、教学、投递三个任务全部成功同步。简历回执：FUTURE_RESUME_EVALOPS_RULES_20260902.md §14、PROJECT_SYNC_RAG_EVALOPS_20260902.md §25 已记录；R12/PDF/指针/历史附件均不变。同步消息也明确本检查点未提交、S5/S6/S7 未完成。
- 提交前最终检查：含重签 HTML 反例的定向集合 50 passed（16.22s）；全仓 lint、632 文件 format check、223 源文件 mypy 和 git diff --check 通过。接下来提交本检查点获取自己的精确 CI，仍不是 S7 最终双 SHA 发布。


## 2026-09-07 第十四检查点：报告原子发布与默认公共导出

第十三检查点 `d6d196b36322af0913bdeb7c606a0740e82a68e2` 的 [CI 34105262335](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34105262335) 已 completed/success；已向简历、教学、投递三个任务补发此精确回执。简历侧反馈已记录上一批到规则 §13/共享同步 §24，当前 R12/PDF/指针/历史附件不变。本节为后续新修改，真实数据库断言仍待自己的 CI。

- 为什么新增独立类型：实验的双组报告不同于单个 Run 的 SUMMARY_REPORT。新增 product_experiment_report 类型，复用既有 ArtifactReference/blob 生命周期；引用归属 baseline Run，但用途由独立类型和父实验报告字段明确区分，不覆盖旧 Run 摘要。
- 0033 增量迁移：父实验增加 nullable report_artifact_reference_id/report_sha256/report_snapshot_sha256，三者必须一起存在或一起为空。复合 FK 同时绑定 reference ID、tenant、baseline Run 和精确 blob SHA，RESTRICT 保护发布引用。旧实验不回填报告。实际存储类型为 VARCHAR/CHECK，不是 PostgreSQL 原生枚举，检查后按现有 CHECK 迁移风格实施。downgrade 首先恢复旧类型约束，存在新报告时会失败并事务回滚，不自动 DELETE 证据；仅用于隔离库演练。
- 发布顺序：在事务外读取原始材料、构建/验证/编码报告并保存 blob；事务内按 Tenant→Experiment→有序 Runs 取锁，复查输入/Run 版本与终态，再登记 artifact 引用及父实验发布指针。先复制调用方 snapshot，防止 await 期间被改。相同 snapshot/bytes 重放同一引用，不同内容拒绝覆盖；blob 写入与数据库不构成单一事务，失败可留未引用对象，由原生命周期清理，不盲删共享内容。
- 幂等导出：首次需要完整结果快照和已授权原始材料；发布后只读同一报告对象，校验 bytes SHA/内部摘要/实验身份，不再读取活动结果、原始数据或重新调用目标。报告整体 artifact SHA、内部逻辑 content SHA、result snapshot SHA、公共 summary 的规范化内层结果 SHA 各有明确用途，不混为一个 hash。
- 公开端点：POST /api/v1/experiments/{id}/export 默认返回 evalops.public-durable-report/1.0 允许字段摘要，不含逐题答案、tenant 或完整结果快照；include_private=true 才返回已发布私有报告的原始字节。两个响应模型进入 OpenAPI，均必须鉴权；Cache-Control 为 private, no-store。运行未终态返回 409，跨租户隐藏 404，证据不支持返回通用 422，不回显原始输入。
- TDD 发现：70 层引用附加字段在包装成报告后超出严格读取深度，旧顺序先登记报告再读取失败，导致留下不可读的“不可变发布”。反例明确失败后，把最终序列化正文的深度/格式验证移到 blob 与数据库写入之前；修复后发布记录为空。没有增加允许深度来掩盖问题。
- 本地测试：真正的 LocalArtifactStore、ArtifactAccessService、报告构建/投影和 API key 哈希鉴权；仅替换数据库边界。发布后移除测试来源读取映射，重放仍返回完全相同 bytes；默认公共响应不含合成 private answer。QA/Agent 重算、零毫秒延迟、篡改/失败病例及旧安全边界均保留。
- 资源边界：进程内最多两个报告导出作业进入处理，CPU 构建离线运行在线程中，取消请求时等待不可中断的线程结束后才释放该作业名额。报告序列化正文最多 512 MiB，严格深度 64；不是 RSS/全部署并发或硬 CPU 截止保证。原始观测总额度另由之前的 worker 预算执行；这里不新增调度器。
- 真实数据库验收已加入：八个相同报告发布者复用引用，其他租户无法读取，不同 blob 拒绝覆盖；公开提交经过实际 worker/claimer/lease heartbeat/成功提交/evaluator 后读取 READY_FOR_ASSESSMENT，再八路并发导出相同公共内容，私有 bytes 与公共 pin 对应、事件 Job ID 与实际请求头相同、导出不重调关闭的 target client。上游 HTTP/DNS/peer 是明确的受控传输夹具，不能称为真实 TCP/TLS、真实模型 A/B 或进程死亡恢复证明。
- 实现过程中：存储工厂原返回标注只声明 ArtifactStore，但两个实际后端都实现删除/列举生命周期接口；将返回类型准确改为 DeletableArtifactStore，无运行行为变更。修复泛型语法、导入排序和迁移字符串行宽，不忽略 mypy/lint 错误。查找过个别不存在的猜测路径，均为只读失败，随后按文件清单确认实际路径。
- 最后扩大回归：332 passed / 1 PostgreSQL skipped，16.17 秒；全仓 lint、623 文件格式和 219 文件 mypy 通过。真实 PostgreSQL、迁移及公开 API→worker→导出用例必须等待本检查点精确 CI。

仍需 durable CLI（提交/等待/恢复/取消/导出）、独立 durable 包验证/易读报告与完整 S5 故障矩阵、S6 文档收口和 S7 双 SHA。当前没有正式 A/B、人评或 production-ready 结论，main/RAG/历史简历链接保持不变。

## 2026-09-07 第十三检查点：共享离线聚合与持久报告重算

第十二检查点 `691ee9335e3ac413dae6e6f88a43fc58cc4ad951` 的 [CI 34102977779](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34102977779) 两项工作已 completed/success，包含真实 PostgreSQL 完整终态快照、重复读取摘要和租户隐藏。以下是其后的新代码，不借用上一个 CI 为本节背书。

- 设计判断：持久导出不能再次调用目标，也不能复制一套 QA/Agent 质量公式。新增只接收观测与冻结上下文的纯 aggregate_product_observations；评分、统计、Agent 专项比较与逐条比较均复用现有函数。先用原 local runner 的 QA/Agent 结果逐字段比对，2 项通过后，再把 local runner 改为调用同一聚合器并移除重复评分暂存。
- 行为变化边界：目标执行仍有原 deadline/窗口/字节限制；纯评分统一放在目标阶段之后，使用已有输入规模与计算量限制，不声称统计 CPU 被 HTTP deadline 硬抢占。无效或缺失观测不能用成功交集生成完整 PASS；缺成本与缺 Agent 轨迹保持 INSUFFICIENT_EVIDENCE。全局来源资格仍 false。
- 新 build_durable_report 将结果快照、输入快照、请求指纹、原始 JSON SHA、规范化 JSONL SHA、dataset version、实际组件 hash/版本与全部病例绑定。原始材料先校验与重新映射；accepted worker 观测经严格 ProviderResult 校验后重算评分，要求保存的评分和缺失原因可以复现。调用链没有 target/client 参数，不重试模型以改善答案。
- 使用独立 `evalops.durable-experiment-report/1.0` 外层合同保存结果快照及其摘要，内部展示结果复用现有模型；不伪造 local 输入 snapshot，也不声称旧 local verifier 已支持 durable 包。完整报告含私有病例/观测，尚未对外发布，后续公共导出必须走允许字段投影。
- 实际身份：结果 execution_id 是父实验 UUID；events 记录真实 Run/Job/accepted attempt ID、序号和开始/完成时间，不伪造 local 的平衡执行顺序。两题 fixture 虽然执行正确，仍因不足 100 题显示 INSUFFICIENT_EVIDENCE。
- TDD 发现四类漏洞：重新计算摘要后，重复 result ID、缺失完成时间、篡改静态观测预算、改变请求 target_version 最初仍能生成报告。分别加入全局结果身份唯一、带时区有效时间、请求推导预算/实际观测字节核验、请求版本与实际 Run 版本绑定后，反例全部拒绝。已有改分、错 dataset/version/config、缺题、旧 attempt 反例同时通过。
- QA 与合法零工具 Agent 的 worker 实际 evaluator 产物均可重算；失败一题时保留另外三条观测，输出 EXECUTION_FAILED 和 target_timeout，不生成逐条成功交集报告。测试是受控进程内算法/合同验证，不冒充 HTTP→worker→数据库→导出的完整 E2E。
- 遇到的问题：初版聚合器的 Literal arm 和 dict 不变性出现两项 mypy 错误，显式类型化修复；两次 Agent 测试补丁因格式器换行未完整应用，核对实际 diff 后重新应用。中间 30 passed 不包含 Agent 参数化，实际加入后为 31 passed；未把失败补丁计作能力完成。
- 最后扩大回归：304 passed / 2 skipped，55.08 秒；跳过分别是 Windows symlink 权限与未配置 PostgreSQL。全仓 lint、618 文件格式、216 文件 mypy 和 diff --check 通过。集合与之前回归重叠，不相加。

仍未完成：报告 artifact 原子发布/并发重放、鉴权公开导出、durable CLI、真实 API→worker→报告和进程故障矩阵、最终文档/双 SHA 与最终跨任务同步。下一步为报告发布接入既有 artifact 生命周期，避免把实验报告混成单 Run summary，也不能用保存 blob 就声称租户所有权已建立。

## 2026-09-07 第十二检查点：有效结果的完整只读快照

第十一检查点 `95462c2b778f5950e40b477840db7481f3b39a32` 的 [CI 34101869013](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34101869013) 两项工作均 completed/success，包含 workflow 显式执行的真实 product persistence 测试。鉴权提交、8 路并发幂等和跨租户隐藏断言已获得该精确 CI 支持，不再仅为本地替身验证。

- 为什么修改：导出不能按“最新 attempt”猜测有效结果，也不能多次 READ COMMITTED 查询后拼接不同时间的 Run/Job 状态。新增 SQLAlchemyProductResultReader，在首条语句设置 REPEATABLE READ、READ ONLY，随后在同一 MVCC 快照内读取父实验、两个 Run、全部 Job 和 CaseResult 指定的 accepted attempt。无目标调用、无写事务、无行锁；并非已经发布的不可变 artifact。
- 身份校验：成功 Job 必须具备结果和 accepted attempt；Job/Run/Case ID、attempt ID/Job/序号一致，attempt 成功且开始/完成时间有效。旧 null accepted ID 不推测回填。快照深拷贝 metrics，数据库对象后续内存变化不改变已返回数据。
- 完整性：未终态拒绝；失败/取消病例保留占位，不删除后只评成功交集。实际病例总数与 Run 三类终态计数一致、两组 case IDs 完整一致；校验输入 snapshot 的 canonical hash。每组最多 10,000 Jobs，查询最多 20,001 行用于检出超限。只读取需要的 Job/attempt/metrics 字段，不额外加载原始 evidence、case payload 和私有异常正文；这不是内存硬上限保证。
- 失败诊断：最初快照没有 error_code，反例出现 KeyError；加入既有 last_error_code，保留 target_timeout 等原因，同时明确不导出 last_error_message。测试使用合成 canary，没有真实秘密。
- TDD 与验证：入口缺失先失败，再实现；17 个定向反例覆盖旧/错绑/未完成 attempt、各 Job 状态、结果缺失及副本隔离。扩大集合为 216 passed / 1 PostgreSQL skipped，9.86 秒；全仓 lint、615 文件格式、214 文件 mypy 通过。真实数据库新增读快照断言需等本检查点自己的精确 CI。
- 数据库验收扩展：QUEUED 实验拒绝最终读取；既有真实八 worker 完成两组后，重复读取应完全一致，每组两题均保留实际 accepted ID/序号，其他租户得到 None，整体摘要可独立重算。没有把测试收集时缺入口的 ImportError 或本机 skip 当数据库 RED/GREEN 证明。
- 开发记录：一次追加测试补丁因格式器已换行而未应用，随后使用实际行重新应用并复现；那次仅 deselected，不计通过。只读查找个别不存在的旧文件名没有修改仓库，后续以实际路径为准。

下一步仍是将此完整快照绑定原始输入，复用现有评分/比较生成可重复报告，再接租户所有权与公开导出、CLI 和故障 E2E。此检查点不宣称质量 PASS、完整 S4/S5 或最终双 SHA 已完成。

## 2026-09-07 第十一检查点：鉴权持久提交与严格 HTTP 输入

第十检查点 `1af50403806a6b37d1bc08e6faeac24a9204a101` 的 [CI 34099588267](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34099588267) 已 completed/success。以下新代码本地扩大回归 199 passed / 1 PostgreSQL skipped，9.82 秒；全仓 lint、613 文件格式与 213 文件 mypy 通过。真实数据库新增断言仍待本检查点自己的 CI。

- 为什么做：已有准备函数和原子仓库，但调用方尚不能经鉴权 HTTP 提交完整实验。新增 DurableExperimentSubmitter 统一请求指纹、租户幂等查询、准备、原始材料保存和原子双 Run 提交，不新增调度器。相同请求返回原实验，即使注册表已移除、服务器 SHA 已改变或实验已取消，也不重新创建任务；同键不同请求返回 409。
- 公开接口：POST /api/v1/experiments 接收 Idempotency-Key、严格 request 与原始 JSON 的 dataset_base64。返回 202、实验/双 Run ID、status_url 和两个 false 资格字段；202 只表示接纳，不代表执行或质量通过。GET/cancel 复用已有控制路径。
- 安全开放：新配置默认关闭；显式启用时必须配置 40 位 product_execution_code_sha，缺失即配置失败。目标仅使用服务器 registry ID/版本，客户端不能传 token 或任意 URL。服务器配置 SHA 是执行身份声明，不是独立运行时证明。当前 scope 仅 DEMO。
- HTTP 限制：先鉴权，再读取正文；总正文最多 16 MiB，读取窗口 10 秒，解码来源最多 10 MiB、控制请求最多 1 MiB。实际流累计字节限制不依赖 Content-Length；压缩、重复 JSON 键、非有限数字及非法 base64 拒绝。不是进程 RSS 或反向代理全链路流量保证。
- TDD 过程：提交路由最初 404，接入后默认 503，再配真实哈希鉴权和实际 mapper/RunService/store 后通过；OpenAPI 起初缺嵌套请求属性，改为内联受控无环模型，公开字段与运行时合同一致。数据库是本地测试唯一持久化替身，不 mock 产品准备和转换逻辑。
- 审查发现并修复：正确 SHA 的非法数据对象仍触发未处理 Pydantic 异常。新增反例先失败，然后仅在不可信 dataset 解析边界转换为 RunInputIntegrityError，HTTP 返回通用 422，不回显合成秘密。不捕获所有数据库/存储错误来伪装输入错误。扩大回归由 198 增为 199 项。
- 真实 PostgreSQL 测试扩展：实际 application lifespan、API key、数据集上传、内容存储、服务和仓库，经 HTTP 8 并发提交应返回同一对任务；其他租户借用 dataset version 为 404、同键变更为 409、取消后重放不复活。此前八 worker 共享窗口测试仍保留。本机不具备 PostgreSQL，不能把收集/skip 当执行证明。
- 开发中两处测试行宽超限由格式器修正；新增 registry fixture 起初遗漏 endpoint，在执行前检查合同补齐。未放宽 SSRF 或允许私网访问。

本节完成的是提交切片，不是整个 S4/S5：有效 attempt 冻结导出、持久 CLI、API→worker→报告闭环、故障矩阵和最终双 SHA 仍待完成。main、RAG、当前 R12 与历史简历链接不变。简历任务已反馈收录上一批公开证据至共享同步记录 §23/简历规则 §12，当前投递版未改。

## 2026-09-07 第十检查点：原始输入保留与租户所有权

第九检查点 `dcf943b8aefbe93c46d8c3145fa1efd630d57b3d` 的 [CI 34098226540](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34098226540) 已 completed/success。本节新修改的本地回归为 215 passed / 1 real PostgreSQL skipped，7.58 秒；全仓 lint、612 文件格式、212 文件 mypy 与 diff --check 通过。

- 问题：只有原始 SHA 而没有保留原始字节，后续不能独立还原转换前的数据。新增 retain_durable_source，在准备/租户授权之后、数据库写事务之外使用既有内容寻址 ArtifactStore 保存原始 JSON；逐字节 SHA 和大小必须匹配，不用规范化 JSONL 冒充原始文件。准备函数本身仍不写 Run/Job 或调用目标。
- TDD：原始保存入口不存在时先失败；实现后真实 LocalArtifactStore 读取的字节与原始输入完全一致且不同于 normalized SHA。准备后追加一个空格会改变原始 SHA，发布前拒绝，测试确认没有创建目标存储目录。
- 原子所有权：复用 ensure_artifact_reference 的 blob 校验、生命周期及引用机制，以 DATASET_SOURCE/tenant 范围登记原始 JSON，不误标为报告。引用与两组 Run/Jobs、父实验在同一事务提交。0032 nullable source_artifact_reference_id 复合 tenant 外键阻止跨租户关联，不回填旧实验，引用被实验使用期间不得删除。
- 失败边界：文件上传和数据库提交不是同一个事务。第二组插入失败或并发幂等冲突可能留下未引用的内容对象，由既有 orphan/reconciliation 流程处理；不盲删可能被其他请求共用的 blob。元数据事务不能留下额外来源引用或半组任务。
- 真实数据库验收已扩展：8 个并发相同请求复用同一父实验/来源引用；经既有 ArtifactAccessService 读取原始字节，其他租户隐藏为 not found；第二组插入故障回滚后来源引用仍只有原来一份。这些新断言须等本检查点精确 CI，不以本地 skipped 代替。
- 检查中修正：一次命令引用了不存在的 test_service.py，实际没有运行测试；随后按文件清单重新执行正确集合。没有将那次命令计为通过。
- 跨任务同步：之前发送被安全审核拒绝。本轮先通过任务列表及简历任务历史核实三个接收任务的归属和既有协作关系，再发送已公开的固定 SHA/CI/日志链接，三个发送均成功。简历当前已因 RAG 更新到 R12，因此要求保留当前 R12 和历史附件，不再误用旧 R11 作为当前版。已要求接收任务思考如何改善叙述/教学/投递口径；发送成功不等同它们已完成更新。

未完成：公开持久提交、有效结果冻结导出、CLI 恢复、完整故障 E2E 和最终双 SHA。原始材料默认受租户权限保护，不因保存成功而自动公开或获得正式质量资格。

## 2026-09-07 第九检查点：静态总观测额度与 worker 永久失败

提交前产品/evaluator/worker/Run/CLI 扩大回归：204 passed / 1 Windows symlink skipped，58.10 秒。第八检查点 `4db8878ac6d7c629943ac0ff8ba7f01ffc20116d` 的 [CI 34097285147](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34097285147) 已 completed/success，包含八 worker 双实验各一槽的真实验收与旧调度回归；不是第九检查点预算的 CI 证明。

- 口径先明确：预算计算复用 local runner 的 ProviderResult.model_dump_json UTF-8 字节，提取 product_observation_bytes 供 local/worker 共用；不是 HTTP 原始响应长度、JSONB 物理占用、审计/失败历史或进程 RSS。HTTP 自身仍执行原响应大小限制。
- 持久模式采用保守静态预留：max_observation_bytes 默认 64 MiB、最大 256 MiB，除以两组全部 Jobs 数量得到每 Job 上限，余数与未用额度不借给其他 Job。4097 字节/4 Jobs 的反例确认每个 1024、合计 4096，不因 max_attempts=2 再领取一份总额。每 Job 唯一 CaseResult 及 accepted attempt 关联保证最终被接纳的归一化观测最多保留一份。这与 local 顺序累计共享池的分配策略不同，必须在 snapshot 中显式区分，不能承诺同一额度下接纳相同题集。
- 严格执行：两组 product-v2 evaluator 配置记录 max_observation_bytes_per_case 和配置 hash；DTO 校验两组配置实际执行该额度，不能只在请求中声明预算。旧内部 basic evaluator 实验未声明此额度时不伪造预算；正式 durable preparer 总是声明并绑定。
- TDD：原 registry 拒绝该新预算字段，先得到失败；接入后恰好等于字节上限可评分，少一字节在评分/成功提交前抛不可重试 experiment_observation_budget_exceeded。错误文本固定，不回显答案。布尔值、非整数、非正数、null 与超过上限均拒绝。
- worker 回归使用实际注册 mock target、实际产品 evaluator 和原 EvaluationWorker，仅替换数据库/lease 边界：attempt 1/2 超额都不提交成功结果，走原永久失败分类，不重试到偶然通过。这个单元测试不冒充真实 HTTP/数据库 E2E。
- 定向验证 evaluator/Run/runner 85 passed；准备/合同/evaluator 18 passed；worker/evaluator/准备 33 passed，集合重叠不相加。212 文件 mypy、610 文件格式与 lint 通过。完整回归结果另记。

仍需公开持久提交、原始输入保留、按 accepted attempt 冻结导出、CLI 恢复与完整故障 E2E。

## 2026-09-07 第八检查点：两组与重试共享的数据库领取窗口

提交前扩大回归 306 passed / 2 skipped，59.28 秒。跳过为本机符号链接权限和未配置真实 PostgreSQL；不得计为成功。静态检查与 diff --check 均通过。

第七检查点 `3bc97307ce50804d9dbc73c568d557ddc5b7a135` 的 [CI 34096255134](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34096255134) 已 completed/success，quality-and-integration 与 compose-smoke 都成功，包括有效 attempt 外键和真实重试断言。本节是后续改动，尚待自己的精确 CI。

- 设计判断：仅在 worker 内放 semaphore 无法限制多个进程；只在领取前查询数量也会读到同一个空位。因此在现有领取事务里增加父实验锁与锁内容量复查，不新增后台调度或第二份可漂移 running 计数。
- 0031 增量迁移：新 Run 保存 product_experiment_id，复合 tenant 外键延迟到事务结束检查；父记录保存 max_active_jobs（新请求默认 4、范围 1–64）。父 ID 在两组插入前生成，仍在一个事务内完整提交。旧 Run/实验不回填，null 的 unmanaged Run 保留原路径且不额外执行实验取锁查询。约束命名使用 op.f，防止约定重复添加前缀。
- 容量是两组所有 RUNNING/CANCELLING Jobs 的合计，重试进入 RUNNING 时也占同一窗口。过期 lease 在原 reaper 改状态前仍占容量，取消中的外部操作也不提前释放名额。不把数据库有效领取上限说成物理外部调用上限，失联远端副作用无法靠数据库撤销。
- 所有既有候选/优先级/公平轮成员查询使用一致的容量筛选，满额实验不会成为队首阻塞其他可执行实验。候选查询只是提示，最后仍必须在父记录锁内复查。满额不新增 JobAttempt、不递增 attempt_count、不分配成功领取序号。
- 锁顺序检查：原路径已经持有 Job 时，新增父实验和 Run 锁都使用 SKIP LOCKED，禁止逆序等待取消路径；Run 使用 NO KEY UPDATE 保留 FK KEY SHARE 兼容。若忙则交还本次领取；父锁持有到原事务结束。未取得有效 Job 的 fair permit 按是否仍存在可执行任务决定保留或 EMPTY，不伪装为 CONSUMED。租约开始时刻移到容量准入通过之后。
- 测试过程：未实现时 shared window 请求因未知字段拒绝、领取 SQL 缺容量条件，分别先失败再通过。准备/合同 6 passed；基础迁移/Run 86 passed；接入后的 jobs/worker/persistence/runs 153 passed。集合有重叠，不相加。mypy 212 文件、610 文件格式和 lint 通过。
- 真实验收已加入原 CI：同租户两个实验，各一槽、每个含两组共 4 Jobs；8 worker 并发领取，每波只能各取一个，满额后返回空；真实成功提交释放后再取下一波，4 波共 8 Jobs 不重复且每个只有 attempt 1。这证明范围限定为数据库 claim/result 生命周期，不是完整公开 API→HTTP target→报告 E2E。本机跳过真实数据库用例，等待本检查点 CI；旧公平性回归也必须通过，未重跑真实模型性能或宣布性能晋级。

下一项仍为持久观测总量限制、公开提交和 accepted-attempt 报告导出；本节不会提前宣布 S4/S5/S7 完成。

## 2026-09-07 第七检查点：有效结果的 attempt 直接关联

第六检查点 `56163a62e96157e7d959c5bcabe5489b5b0ea3ec` 的 [CI 34095414644](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34095414644) 已 completed/success。第七检查点提交前扩大回归：303 passed / 2 skipped，56.19 秒；跳过分别为 Windows symlink 权限与未配置本地真实 PostgreSQL，均不算通过。

- 先检查评分边界：citation_precision_min 与 agent_comparison_policy 是实验级比较阈值，local runner 在 assessment 阶段使用；逐题 worker 只输出同一评分公式的观测。没有把比较配置重复加入 evaluator，也没有把此处误报为评分缺陷。后续 durable 聚合仍必须使用冻结 request 中的比较阈值。
- 确认需要补齐的事实：旧 CaseResult 仅绑定 tenant/run/job，成功 attempt 身份依赖审计关联，没有直接外键。新导出不能用“最近一次尝试”猜测哪条结果有效，所以新增 nullable accepted_attempt_id，并用 (accepted_attempt_id, job_id) → JobAttempt(id, job_id) 复合外键禁止串 Job。
- 0029→0030 增量迁移先有失败测试，再实现；不回填旧数据、不修改历史证据。外键 DEFERRABLE INITIALLY DEFERRED：事务结束必须完整一致，同时允许原有整组 Job/result/attempt 清理在同一事务内完成，不依赖逐条删除次序。不是允许留下悬空引用。downgrade 仅供隔离环境，生产仍采用关闭入口或前向修复。
- 成功提交测试先显示 accepted_attempt_id 为 None，再由原有租约/版本保护的 commit_success 保存实际锁定的 attempt.id，不新增另一条结果写路径。另加两种序号错配反例：原会继续进入结果聚合，现于任何新增结果/事件前抛 AttemptNotActiveError；正常 retry 和心跳版本语义不变。
- ORM 回归最初因 job_id 新增外键目标而失败，更新预期以检查两条关联都存在，没有放宽数据库规则。定向 jobs/worker/persistence/runs 151 passed；一次测试行宽超限已由格式器修复。当前 211 文件 mypy、607 文件格式和全仓 lint 通过。
- 扩展真实 PostgreSQL 并发测试：实际领取/成功后检查关联；错误 claim 序号拒绝；跨 Job 改绑及单独删除被引用 attempt 必须事务回滚；reaper 后实际领取 attempt 2，旧 lease 拒绝，新结果只绑定 attempt 2。本机没有真实 PostgreSQL，新增断言等待本检查点精确 CI，离线 SQL 与单元测试不能代替它。

此项是 S4 accepted-attempt 导出的数据前提，不是完整导出接口。公开提交、实验共享并发/观测总量、不可变报告与完整故障 E2E 仍未完成，不修改 main、RAG 或旧简历链接。

## 2026-09-07 第六检查点：持久提交准备、总尝试预留与输入一致性

提交前重新执行产品、Run、evaluator 与 CLI 回归：180 passed / 1 Windows symlink skipped，59.60 秒。上一轮完整输出未留存，所以重新运行而非推测结果。全仓 lint、605 文件格式检查、211 文件 mypy 与 git diff --check 通过。真实数据库预算断言仍待本检查点精确 CI。

第五检查点 `52ab9c7d3eee524fce590fa11e6d327efb8bbeb1` 已推送，精确 [CI 34092870938](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34092870938) 的 quality-and-integration 与 compose-smoke 均 completed/success，包含新 deadline 数据库往返与迁移验证。本节是此后的新修改。

- 持久提交准备：新增严格 DurableExperimentRequest 和 prepare_durable_experiment，只准备、不写 Run/Job、不调用目标。接收同租户不可变 dataset version、原始 product JSON 的 SHA、两组 registry target_id/版本、policy 与尝试/时间额度。逐项复用原 mapper、LocalArtifactStore/RunService、产品评分标签预检与目标输入投影，在数据库写事务外完成。测试通过真实 mapper、文件存储与 RunService，仅替换数据库边界。
- 原始与规范化身份：原始 JSON 字节先验 SHA 校验，再映射 JSONL；两组准备的已授权 dataset hash 必须等于映射产物。篡改 prompt 并重算原始 SHA 仍因存量版本不匹配拒绝，未知 registry version 拒绝。来源 SHA 明确 CLIENT_DECLARED，server evalops SHA 是配置身份而非独立运行认证。原始字节不自动永久保留，这仍不是独立原始数据公开复核。
- 固定配置：使用独立 durable-experiment-input/1.0 快照，保留规范化 request、mapping 版本、两种数据摘要、组件配置摘要/版本与共同绝对 deadline，不伪装成 local snapshot。来源字段不允许 URL 用户信息、query 或 fragment。接口初版只允许 DEMO，不能通过 FORMAL 标签绕开来源资格。
- 总尝试预算：默认 max_total_attempts=20000，可声明 1–200000；每 Job 的最大尝试保持 1–10。两组所有 Jobs 的最大尝试数一次性求和，超总额拒绝。用既有每 Job 的 retry/reaper 上限执行，不新增第二计数/调度循环，不允许两组各领取一份总额度。保守预留不回收未使用额度，不代表实际消费、模型内部调用数或硬美元预算。
- 检查中纠正一个断言：集成用例有 4 Jobs，但 Run 默认 max_attempts=3，所以应预留 12 次而非 4 次；单元夹具 max_attempts=1 时才是 4。没有修改既有策略去迎合错误计数。数据库预算与完整快照 hash 断言待本检查点 CI。
- 嵌套可变性：frozen dataclass 不会冻结内部字典。构造后改单组 case 的反例原会先访问数据库；repository 现在在首次 await 前复制两组与 snapshot，并再次触发合同验证。预算注入与完整 snapshot hash 统一由同一函数生成，避免新增字段后沿用旧 hash。
- 解析一致性：spec、policy 和原始 dataset 原会接受重复 scope/bootstrap_seed/prompt 的最后一个值。3 个反例先失败，输入端复用严格 JSON 后通过；原始字节 hash 算法不变。聚合数字 1e999 原会解析为 Infinity 绕过常量检查，现也拒绝解析后非有限值。
- 定向验证：上述新准备入口 4 passed，连同持久合同 5 passed；此前产品/Run/evaluator/CLI 集合 176 passed / 1 symlink skipped。集合有重叠，不相加。当前 mypy 211 文件通过。测试函数一行过长导致 lint/格式检查失败，已使用格式器修复，未降低检查规则。

仍未开放公开实验提交入口：共享并发窗口、观测总量和最终 accepted-attempt 导出必须接好并验证后再开放。本准备函数是 S4 内部前置能力，不能当作 API→worker→报告 E2E 已完成。继续保留原计划的故障矩阵、最终双 SHA 与跨任务最终同步要求。

## 2026-09-07 第五检查点：类别诊断与持久截止时间

提交前受影响集合：281 passed / 1 Windows symlink skipped（51.67 秒），210 文件类型检查、603 文件格式与 lint 通过。测试覆盖产品/CLI、Run、worker、Job 与迁移。真实 PostgreSQL 新断言仍等待本检查点精确 CI，不能用定向单元测试替代。

第四检查点 `f5af8cfa88a3a44e5ecc6824d112ba98337435cb` 已推送，精确 [CI 34090774472](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34090774472) completed/success。以下是后续新改动，不由第四检查点 CI 代替验证。

- 类别诊断：按同一固定 category 分组，复用 build_metric_diagnostics，不复制评分公式。保留 policy 要求但没有题目的类别；样本不足标 SMALL_SAMPLE，无题标 MISSING_CATEGORY，逐指标有效配对不足列 undersampled_metrics。构造两类一升一降与缺费用反例，证明局部退化不会因总体混合而不可见。实际超时运行也保存全部类别分母和缺测提示。私有报告增加该区，公开 v1 golden 字节回归保持通过。该区 DESCRIPTIVE_ONLY，不增加新的显著性检验或 PASS。
- 持久时间预算决策：为原 Run 增加 nullable execution_deadline_at，用 0029 增量迁移，不回填旧 Run，不在 retry/claim 时重新计算期限。NewRun → ORM → ClaimedJob → 原 worker 传递同一时刻，双组 DTO 拒绝不同截止时间。不新增调度循环，尚未开放提交 API。
- 反例与效果：首次/第二次 attempt 在期限已过时原无此合同；加入检查后，在创建目标前产生不可重试 experiment_deadline_exceeded。慢调用跨越总期限原最终记录可重试 HTTP500；改为将单次 timeout 与总剩余时间取最小值，明确区分总预算耗尽与目标自身超时。调用返回后再检查期限，不接受已过期的返回值。采用 UTC 墙钟/合作式异步取消，不承诺撤销远端副作用、CPU 抢占或无时钟漂移。
- 兼容性：旧 Run 截止时间为 null，保持原 per-case timeout 与重试路径。未给全部既有任务强行添加截止时间。过期的排队任务仍需原 worker 领取后结束，不宣称在 worker 停机时自动即时终止。
- 验证：类别/runner/report 55 passed；worker/jobs/迁移/双组合同 72 passed；此前相关 runs/ORM 47 passed。集合重叠不相加。mypy 210 文件通过。新增真实 PostgreSQL 双组 deadline roundtrip 断言须等待第五检查点 CI；离线迁移 SQL 只证明生成的升级/回退语句，不是本机数据库演练。
- 外部只读核验：RAG 精确公开交付已完成摘要、775 服务行/87 CSV 聚合/2 组配对/800 检索行重算，详见 rag-runtime-delivery-readonly-verification-20260907.md。CSV 核验采用表格技能的只读源数据/分母/缺失值原则，不创建或改写表格。该结果不升级 EvalOps 的正式质量资格，也不冒充私有重放。

剩余共享预算：并发窗口、跨两组及重试的总调用额度和观测体积仍须实施/验收；只有共享截止时间基础不代表 R10/S4 已完成。继续推进持久提交、accepted-attempt 导出、真实 worker 故障 E2E 与最终双 SHA。

## 2026-09-07 第四检查点：固定输入与聚合解析边界

提交前验证：product_experiments 与产品 CLI/证据集合 132 passed、1 Windows symlink skipped（51.65 秒）；mypy 210 个文件、ruff check 和 600 文件格式检查通过。已把第三检查点精确 CI 和本节待推送内容、未完成项发给简历/教学/投递三个任务，请其思考资料改进，不改已投简历及链接；发送成功不等于对方已完成材料调整。

第三检查点 `28a2b9da9b97bdc0a1e5955069e6cf1b7230ccf5` 已推送，精确 [CI 34089484214](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34089484214) 的 quality-and-integration 和 compose-smoke 均 completed/success。本地提交前 161 passed / 1 Windows symlink skipped，598 文件格式与 208 文件类型检查通过；不与以前计数相加。

- 提交合同：同一 dataset ID/hash 不保证内部 DTO 携带同样题目。复现后增加同 actor、规范化 JSON 摘要相同的有序 cases、相同 evaluator 类型/版本/配置约束。不比较 Python 的宽松 bool/number 相等性。此合同仍不是已开放的提交 API。
- 快照反例：修改 policy 而不改摘要、重算摘要后换 dataset、未知 schema/字段、改 source/scope、直接删除完成结果快照，原导出均接受。逐步增加内容摘要、严格已知模型、数据集/来源/任务/范围交叉绑定；完成的 v2 必须有快照。v1 和尚未开始的 INPUT_REQUIRED 包不被误称具有此保证。
- 兼容修复：原公开隐私测试用任意 internal_url 字典替代快照，现在被正确拒绝。改为在合法 source_repository 中植入相同秘密标记，并同步模拟身份/摘要，保留原有答案、命令、内部 URL 不出现在公开包的断言；不是放宽验证器让错误夹具通过。
- 保证范围：原 spec/policy 字节未包含在本快照中，无法独立重算它们的原始字节 hash；配置内容 hash 可复核但不是签名或独立来源认证。没有伪造原文件，也没有用新代码重写旧证据。
- 聚合读取：重复 decision 字段即使 hash 正确也必须拒绝，反例先失败后通过。抽出共用 decode_evidence_json，拒绝重复字段、非有限常量和超过 64 层嵌套，产品 verifier 复用同一规则。聚合 reference 限 1 MiB、artifact 限 16 MiB，均最多读上限加一字节；1 MiB 空白填充反例已复现/修复。不是内存 RSS 或恶意文件系统并发替换的完整保证。
- RAG 通知其真实模型测量结束，本轮仅确认协调解除。其 runtime-service-contracts/1 和 runtime-delivery-evidence/1 不冒充 enterprise.agent-run/1.0，不把聚合数字拆成虚构逐题结果。仍不修改 RAG 仓库。

本节改动尚需独立提交/精确 CI，第三检查点 CI 不覆盖它们。剩余重点仍为持久提交/共享预算/结果导出与 worker 故障验收；不能因证据验证加固而宣布整个计划完成。

## 2026-09-07 第三检查点：控制接口、缺测诊断与兼容性

第二检查点 `90ff44a9562191e9f55024d73e395c278eb8be10` 已推送，其精确 [CI 34086968459](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34086968459) completed/success，包含真实 PostgreSQL 原子双 Run 幂等/回滚集成及 Compose smoke。这不能作为本节新修改的 CI 证明。

- 取消：在 GREEN 状态提取现有 cancel_run_in_session，不复制取消状态机；父实验取消按 Tenant → Experiment → 排序后的 Runs → Jobs 加锁，在同一事务取消两组，重复取消不增加父版本。它不会撤销已经发生的外部服务副作用。
- 控制入口：增加鉴权 GET /api/v1/experiments/{id} 与 POST /{id}/cancel。状态从两组 Run 派生，全部执行成功也只叫 READY_FOR_ASSESSMENT，不叫质量 PASS。未认证请求从原来的 404 复现到正确的 401；授权查询、跨租户 404 和双组取消验收已追加到真实数据库集成，待本检查点 CI。
- 早期拒绝：产品 evaluator 要求 product-v2 版本、规范化映射题目和显式评分标签。原本会创建 Jobs 的不合法数据集，以及会先访问数据的错误 evaluator 版本，均先写失败测试再修复。拒绝信息不回显私有题目。
- 证据配对：拒绝 arm 角色错误或两组同 case_id 却 prompt/category 不同的包，不能仅凭 hash 自洽认定配对有效。
- 缺测诊断：即使费用缺失阻止完整门禁，仍展示可用质量/延迟的配对覆盖、胜负/持平和平均差。全部标记 DESCRIPTIVE_ONLY，无显著性或正式结论。极大但有限费用的求和溢出先复现，再使用缩放后求和；未知费用仍不是零。
- 兼容性问题：给 HTML 增加诊断区会改变公开 v1 的确定性字节。提取已推送检查点的固定合成样本摘要并编写 golden 回归，先失败，再仅为私有报告增加诊断区。公开 v1 原渲染保留，不重写历史证据。
- 定向结果：产品/runs/evaluators/CLI 160 passed、1 Windows symlink skipped；随后公开渲染兼容性集合 10 passed；mypy 208 个文件通过。集合重叠，不相加。真实取消/隔离尚待精确 CI，Windows 无权限创建真实符号链接不记为通过。
- 资源协调：RAG 任务正在做真实服务配对性能测试，本轮不操作其仓库、不启动 GPU/Ollama 负载，完整数据库和并发验证使用远端 CI，本地只做定向回归。

尚未打通：鉴权实验提交与 CLI、共享实验预算、固定快照、从已接纳 attempt 导出结果、真实 worker/故障 E2E、最终双 SHA 收口。上述控制接口是中间能力，不是 S4/S5 完成声明。

## 2026-09-07 后续切片：精确 CI 与持久实验基础

第二检查点提交前：受影响集合 **252 passed, 1 symlink skipped in 33.81s**；随后补“产品 worker 不静默忽略评分覆盖参数”，反例先失败，限制配置为现有 max_attempts 后 evaluator/runs **37 passed**。全仓 lint、格式与 205 文件类型检查通过；0027→0028 的离线 SQL 成功生成并人工核对复合外键/幂等/RLS，未在本机执行 DDL。上述集合重叠，不相加。新数据库集成仍须等第二检查点精确 CI。

- 工作分支检查点已提交并推送：`8cbad06f32f9a0e010c35da7aa97e68b08007e2f`。精确 [CI 34085325610](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34085325610) 已 completed/success，包含完整 quality-and-integration 与 Compose smoke。该结果只覆盖该提交，不覆盖下面的未提交修改。main 仍为 `50af0603ff76615f3cf2c54fba3230e1cee7647f`。
- 证据继续收口：新增 64 层 JSON 解析前深度限制；新增 arm 与主结果的 dataset/source SHA 交叉验证。反例分别是深层 JSON 原本仅报未知 schema、两份文件彼此一致却与主身份冲突；修复后定向测试通过。
- 数据映射：map_product_dataset 复用 local 的 parse_product_dataset，原始 JSON 字节摘要与规范化 JSONL 摘要分别记录，mapping_version 固定。目标可读上下文只从 public_context 复制；原 case/标签保存在 evalops_product_case 私有评测元数据中。显式零工具字段保留，不把缺字段补成已提供。mapper 与 runner 44 项通过。
- 共用评分：从 HTTP provider 提取 normalize_product_observation，把 local 的评分入口命名为 score_product_case。worker 注册 product_qa_v2 / product_agent_v2 薄适配器调用同一实现，旧三个插件的 builtin-v1 不变。QA 来源 ID recall/precision、Agent 正确零工具拒绝得到回归；缺费用/缺观测不填零分或成功分。相关 evaluator/product 集合 90 项通过。它还不是从鉴权实验 API 到 worker 的 E2E 证明。
- 事务基础：GREEN 状态机械提取 insert_run_and_jobs，保留旧 create_or_replay 的事务所有权和冲突处理，runs 26 项通过。新增 NewProductExperiment 的同租户/同数据集前置合同，以及 product_experiments 控制表、租户复合外键、幂等唯一约束、RLS 和 0028 增量迁移，不回填旧 Run。新 repository 在一个 begin 中插入两组及父记录，只有指定幂等唯一冲突允许查询重放。
- 真实验收已编写并加入 CI：8 个并发重复提交只保留一对 Run/4 Jobs；不同请求冲突、跨租户查询隐藏；在第二组 ORM 插入边界注入错误，确认已处理过第一组后整体回滚，无新父记录或孤立 Run/Jobs。成功后仅删除测试专属租户对象；共享 blob 不盲删。当前本地仅 collection/类型检查与跳过，尚未获得这项新数据库测试的成功证据。
- 本地模型/既有迁移/输入合同集合为 50 passed / 1 integration skipped；类型检查随新模块为 205 source files。一次测试遗漏独立 basetemp，触发既有 pytest 临时垃圾目录 77 条权限清理警告；未手工删除那些目录，后续恢复独立 basetemp。

仍未完成：持久实验鉴权 API/CLI、共享全实验限额、取消/导出与固定快照、真正 worker E2E/进程故障、完整缺测与切片报告、最终双 SHA/两次精确 CI 收口。当前新增 repository 不能单独作为已发布产品入口宣传。

## 2026-09-07：恢复执行、证据读取与发布边界

提交前受影响集合复测：product_experiments、CLI/证据、runs、HTTP target 共 **188 passed, 1 skipped in 28.34s**；全仓 ruff check、585 文件格式检查通过；mypy app/scripts/integration/concurrency 的 201 文件通过。历史 scorecard 与 final evidence manifest 只读校验通过。下一步为工作分支阶段提交/推送与精确 CI；不是 S7 最终代码/文档双提交收口。

本地全量非集成检查点：**1020 passed, 1 skipped, 39 deselected in 367.17s**，JUnit 位于忽略目录 artifacts/trustworthy-v2-checkpoints/nonintegration-20260907.xml。运行期间另补报告状态颜色和 Run 准备入口，因此最终提交仍需受影响集合复测与精确远端 CI，不能把此数直接贴作最终 SHA 验收。

S4 前置切片：新增 SQLAlchemyRunService.prepare_run，复用现有租户 dataset 授权、registry target 限制、内容校验及快照构造，但不提交 Run/Job；create_run 继续拥有原有幂等检查、遥测和提交逻辑。先以数据库边界记录器验证“准备不持久写入”失败，再提取实现；runs 集合 26 passed，CI 范围 mypy 201 source files 通过。这只是双组共享事务的前置接口，不是持久实验已经落地。

报告状态切片：原 HTML 所有状态都使用成功色；5 个状态矩阵反例失败后，明确成功/失败/待定样式，未知状态按待定，报告集合 8 passed。不改变任何质量决策。

跨任务同步已发送至“优化简历内容与结构”“两个项目学习与面试答辩｜RAG + EvalOps”“秋招投递总控（找岗位+定制简历+台账）”，附完整本地记录路径与本轮能力/限制，明确未发布不能替换已投材料。简历任务已回复并记录到 FUTURE_RESUME_EVALOPS_RULES_20260902.md 第 10 节，保持 R11 不动，待精确代码/证据 SHA 与 CI 后再考虑 R12。

追加公开导出切片：秘密标记同时放入实验名称、答案、快照内部 URL 和命令文本，旧默认导出泄漏而失败。新默认 public 使用独立严格摘要模型，不透传自由文本或原始比较对象；private 显式保留完整包，旧完整性测试通过明确 private 模式继续验证，并未删除。公开材料绑定同次私有 result 字节 hash，但只获得 PUBLIC_PROJECTION_ONLY 保证。另一个反例在 HTML 追加秘密并更新 manifest 的 hash/size，原验证仍接受；现在要求 HTML 与受限摘要渲染完全一致。该公开报告版本的渲染需要随合同冻结维护，未来不能无版本地改变后声称旧包仍确定性一致。

检查点：发布前自校验后 CLI 为 28 passed / 1 skipped；首次公开分离后为 29 passed / 1 skipped；公开 HTML 反例修复后定向 3 passed。mypy app scripts 随新增模型为 182 source files。当前全量非集成测试正在运行，尚不能写通过。

本节更新前文阶段记录；旧记录中的“尚未完成”是当时状态，不作为当前进度判断。仍未提交或推送本轮实现，不将本地检查冒充远端 CI。

- 恢复原因：上次审批系统返回 refresh token revoked，命令未执行。此次普通沙箱仍初始化失败，但只读审批命令成功；随后按原授权恢复工作，没有绕过审批或改动凭据。
- JSON 歧义：构造重复 production_ready 字段，旧验证器按最后一个值覆盖并接受；使用 object_pairs_hook 拒绝重复字段后通过。此规则也应用于 result 和 arm JSON。
- 文件种类：原验证器接受任意额外文件。现在只接受本合同的 result.json、report.html、baseline.json、candidate.json；未来增加快照文件必须显式升级允许列表及测试。
- 读取限制：1 MiB + 1 的 manifest 原本在完整读入后才报告 JSON 不可读；改为最多读取上限 + 1 字节，准确报告尺寸超限。manifest 上限 1 MiB，单产物上限 256 MiB；这不是进程 RSS 的硬上限。
- 链接：实际 Windows 链接创建返回 1314，真实链接测试保留并跳过，不能计为通过。文件系统边界注入链接状态的反例先失败，增加链接/解析父路径检查后通过。此检查不声称抵抗同一目录恶意并发替换的所有 TOCTOU 攻击。
- 发布：磁盘边界模拟 report.html 写入失败，旧实现残留已发布 result.json。现在使用同文件系统临时 staging、独占导出锁、验证后 rename；失败时清理本次临时目录，不发布半包。已有非空输出不覆盖。仅允许移除空目标目录，非递归。进程被强杀可能留下锁或临时目录，尚需恢复流程与真实进程测试。
- 自校验：构造完成结果题数不一致，旧 writer 仍发布。新 writer 发布前调用 verifier。旧篡改测试使用“0 题 DEMO_PASS”假夹具，现改为合法 INPUT_REQUIRED，保留篡改 hash/size 拒绝断言。
- 检查点：在 staging 修改之前，产品与 CLI 集合为 **100 passed, 1 skipped in 18.11s**；mypy app scripts 为 **181 source files passed**。这些不是最终全量结果，后续检查另记，重叠测试不相加。

此前连续实施还已落地：QA 来源 ID recall/precision（不等于语义忠实度）；Agent 引用不适用而非补 1；qualification 与 non-regression 可配置且分别报告；类型敏感工具参数精确匹配；预期拒绝终态；固定 seed 的逐题平衡执行与事件时间记录；单 case 1 MiB、观测总量默认 64 MiB/最大 256 MiB；严格 aggregate v2 与有限保证的 legacy 分开，离线校验明确 NOT_RUN 在线核实。旧全量检查点 1008 passed / 39 deselected 不是这些最新修改后的最终证据。

剩余重点仍包括公开脱敏导出、严格输入快照绑定、切片与缺测覆盖率、持久实验接入 Run/Job、真实进程故障/租户集成、最终代码与证据双 SHA/CI，以及教学和简历任务同步。没有宣称全计划完成或 production-ready。

## 继续实施批次：退出合同、输入身份、Agent 边界与证据关联

本批沿用已批准方案与 tdd 技能，不创建新目标、不修改 main。由于输入快照与证据包直接关联，把相关完整性反例一并修复；这不代表跨过未完成的阶段验收，也不宣称 S2/S3 整体完成。

1. CLI 退出合同：新增公开 experiment_exit_code 的完整状态矩阵，初次因接口不存在失败；实现后所有已知状态按约定映射，未知状态/门禁返回 3。文件系统边界注入 KeyboardInterrupt 时，原 main 把中断传播出边界；补处理后安全返回 130。CLI 当时 16 项通过。中断测试证明的是命令边界合同，不冒充真实 worker 进程恢复。
2. 输入快照：反例要求同输入两次运行的快照相同、execution ID 不同，修改 policy seed 后内容身份不同；初次缺 input_snapshot 字段而失败。现在从实际读取的一份 spec/policy 字节计算摘要，并保存规范化配置和规则；dataset 使用已校验的精确 hash。没有在导出时重新读取文件。名称与本机文件路径不进入规范化内容身份；原文件摘要另存。相关 product/CLI 当时 65 项通过。
3. 零工具：原预检用空元组判断缺 allowlist，导致合法零预算/零调用输入失败。改为检查是否显式提供字段，零工具可执行；再加入缺 allowlist、预期越权工具、预期超预算的反例，后两项原本漏检，补一致性校验后通过。
4. 参数结构比较：两个反例显示 Python 把 True 与 1、嵌套 False 与 0 评为完全匹配。新规则显式区分 bool/number；1 和 1.0 按 JSON 数值等价处理；对象键顺序不影响结果，数组顺序影响结果。不是工具 JSON Schema 有效性验证，只是类型敏感的精确结构匹配。
5. 预算：恰好使用 1 次/限额 1 且报告 budget_exhausted=true，原本算违规。改成实际调用数超过上限才算违规，耗尽字段继续保留在原始观测。同步调整之前把“耗尽”当“超限”的断言，没有删除工具错误/终态保留断言。product 当时 59 项通过。
6. 证据包：先后复现完成包省略两组条目、重算 candidate 文件 hash 后来源 SHA 与 result 矛盾、重算 result hash 后题数谎报、结果自称 formal allowed、未知结果 schema。原校验都没有拒绝对应反例。现在按完成状态要求两组文件，逐内容比对 arm/result，核对题集/唯一性/计数/对比集合，并做严格结果模型与 manifest 版本校验。CLI/证据测试当时 21 项通过。

本批仍在实施和验证。上述测试集合重叠、不相加。快照尚需严格 schema/版本实现绑定与导出配套；尚未完成引用适用性、完整比较 policy、持久执行和真实集成。后续检查结果继续追加，不使用前批 914 单测数充当本批全量结果。

## 总状态

- 方案：`docs/plans/trustworthy-evaluation-product-execution-plan.md`（v2）。
- 用户已批准按方案实施；工作分支 `codex/trustworthy-evaluation-product-v2`。
- 起始代码/远端 main：`50af0603ff76615f3cf2c54fba3230e1cee7647f`。
- S0 已完成基线与合同选择；S1 核心修复已落地，仍有验收缺口；与预检/归一化直接相关的 R1/R5 前置防护已加入。S2–S7 未完成。T1–T4 不默认实施。
- 未修改 main、RAG、历史证据，未宣称正式质量或生产资格通过。

## S0 / 2026-09-05：基线与执行判断

修改前状态：只有本任务生成的方案与补充审查文档未跟踪，没有用户业务源码修改。远端 main 与审查 SHA 相同，目标实现分支不存在，因此从当前基线创建独立分支。

实际检查：Python 3.12.13；定向基线 `tests/unit/product_experiments tests/unit/scripts/test_product_experiment.py tests/unit/targets/test_http_rag.py tests/unit/jobs tests/unit/workers` 为 **139 passed in 1.72s**。证据校验命令执行，scorecard 返回 PROJECT_SCORECARD_VERIFIED，仍为 READY_WITH_EXPLICIT_LIMITS / NOT_VERIFIED / NOT_READY_NEGATIVE_SCALING_AND_QUALITY_INPUT_BLOCKED。

环境问题：Docker 不在 PATH，常规 Docker Desktop CLI 路径也不存在。集成环境尚未就绪，不安装新软件、不借用其他项目数据库；先推进可独立验证的修复，再检查安全可用的隔离环境/分支 CI。此限制不能写成集成通过。

实施原则：使用 tdd 技能，一次只为一个公开行为写失败回归，再最小修复。接口和验收采用用户批准的方案，不重新发明模型、调度器或重试系统。

S0 合同决定：CLI 默认 automated，新增 formal 门禁；质量 FAIL=1，缺输入/正式待定=2，内部错误/导出失败=3，中断=130。新结果语义另有版本，不改写历史文件。HTTP 输入与评测标签隔离；执行 label/content/execution/attempt 身份分开。详细 R1–R13 行为清单与兼容/数据/故障约束见主方案第 2–8 节。

教学要点：基线测试通过只能说明既有断言满足；缺陷需要新的反例证明。独立分支保护发布入口，但不会自动证明新改动正确。

## S1-01：CLI 质量失败必须传递给调用方（定向通过）

原因：旧 CLI 对 DEMO_FAIL/AUTOMATED_FAIL 返回 0，自动化调用方无法正确阻断。

测试设计：复制公开 demo 到临时输入，将 candidate 答案全部改错并更新合法数据 hash；运行实际 Python 子进程，不 mock runner。期待 DEMO_FAIL、非零退出码，同时仍生成可读失败产物。

RED：真实子进程返回 0；GREEN：失败报告保留，退出 1。新增 formal 门禁后，demo 即使通过也退出 2。执行失败退出 3。随后补了顶层输入和导出异常回归，详见 S1-04；中断和穷尽状态映射尚未完成，不能把这条记录当成全部 CLI 合同完成。

## S1-02：网络输入、轨迹与失败分类（定向通过）

为什么修改：旧 metadata 选项会把参考答案等评测信息发给目标；HTTP Agent 丢失工具结果；网络失败被转换成质量错误。这些问题会污染分数而不一定让旧测试失败。

实际修改：只投影显式 public_context；通过公开 runner 的 HTTP client/resolver 边界注入做测试。保留平铺 Agent 字段，并新增既有 AgentRunArtifact/v1 的显式投影，校验题目/答案、事件标识、调用和结果配对，记录原始终态和内容 hash。缺少可评分轨迹返回 INSUFFICIENT_EVIDENCE；401/429/503 等基础设施错误记录安全原因码并返回 EXECUTION_FAILED，不制造空答案和工具质量分。

RED/GREEN：标签泄漏断言先失败后通过；映射测试先因缺少公开注入接口失败，补实现时误将参数插入结果构造，导致 Pydantic 多余字段错误，检查实际调用位置后修复；错误分类反例从 DEMO_FAIL 改为 EXECUTION_FAILED；缺轨迹从错误评分改为证据不足。日志不保留真实令牌或上游正文。

效果与限制：新结果/manifest 使用 2.0，旧版本仍可读取；只对明确公开上下文做投影，不声称能检测使用者主动放入 public_context 的秘密。没有伪造缺失参数；旧轨迹缺工具参数时仍不足以支持参数精确匹配。正式资格、费用缺失和严格证据包验证尚待后续阶段。

## S1-03：有界读取、执行窗口与身份（定向通过）

实际修改：HTTP 默认响应上限 2 MiB，可配置至 16 MiB；读取时限制字节数并保证关闭响应；请求 identity 编码并拒绝压缩响应，避免解压绕过限制；总 HTTP timeout 包含 DNS 和流读取。数据文件最多 10 MiB、2 至 10,000 题；执行采用固定消费者窗口而非一次创建全部题目任务。

RED/GREEN：流读取超限测试先被未支持配置拒绝，实现后稳定返回大小限制错误并关闭流；慢流测试原来触发测试外层 timeout，修复后触发目标 deadline；空/超大数据原来被接受或进入解析，修复后在校验边界拒绝。任务窗口测试原来观测到 121 个活跃任务，修复后满足测试上限，runner 定向 14 passed。这是资源边界证据，不是吞吐量或生产容量证明；仍保留 O(N) 的有界输入/结果存储。

身份：每次运行生成 execution UUID，再派生 arm/run/job/attempt 标识。同配置运行两次的 job ID 原来相同，新回归证明不同。尚未实现持久恢复，因此不宣称 local 路径具备恢复语义。

预检：新增 --validate-only；实际 CLI 验证 120 题/240 计划执行，不调用目标、不创建输出目录。随后统一预检与执行的输入准备，详见 S1-04；不能只凭 READY 推断正式试验可开始。

## S1-04：错误边界、共享预检和计算预算

逐步执行：

1. 写真实 CLI 非法 scope 反例。原行为退出 1，stderr 包含合成私有输入值及 traceback；改为固定 experiment_input_invalid、退出 2，反例通过。
2. 写真实导出路径冲突反例，输出位置是已有文件。原行为打印路径并退出 1；改为安全执行/导出原因码、退出 3，同时确认原文件内容未变。CLI 七项定向通过，不以此代替未测试的中断语义。
3. 在绿灯回归基础上抽取 `_prepare_experiment`，预检与实际运行共享 spec/dataset/policy 和 Agent 输入校验。相关 43 项通过。这样修改是为了避免“预检接受、执行拒绝”的双重校验漂移，不是另造框架。
4. 增加实验目标执行阶段 deadline。旧 spec 不支持该字段；实现后等待中的调用被取消，已完成 baseline 的 120 个观测保留，未完成题记录 experiment_deadline_exceeded，没有虚假对比。默认 3,600 秒，最大 86,400 秒。同步解析和统计仍依靠大小/工作量预算，不宣称 CPU 可被硬抢占。
5. 三个预检反例：spec 超过 1 MiB、policy 超过 1 MiB、bootstrap_resamples=1,000,000。原行为均接受；增加限量读取和题数×resamples 预算后全部拒绝，未实际执行巨量采样。上限是保守安全预算，不是性能测试得出的容量结论。

遇到的问题：总 deadline 回归最初设 20 ms，在并行完整回归期间，可能尚未进入目标就到期，导致“流已关闭”断言不成立。这不是取消代码失效。调整测试为 500 ms 启动裕量、外层 5 秒保险，目标仍永久等待，不放松取消、部分观测和失败原因断言，runner 27 项通过。

## 与 S1 共用边界的 R1/R5 防护（不代表 S2 已完成）

正式资格：新反例证明旧预检把 FORMAL fixture 标为 READY。当前 v1 spec 不含独立来源/协议材料合同，因此在执行前 fail closed：fixture 返回 FORMAL_FIXTURE_NOT_ELIGIBLE，HTTP 返回 FORMAL_PROVENANCE_CONTRACT_REQUIRED。缺凭据原因仍独立保留。尚未完成整个正式证据合同和执行后资格计算；不是把 FORMAL 功能改成已验收。

未知成本：最初构造的 usage 少了 output_tokens，被核心响应合同先拒绝；修正为有效 usage 后，确认旧实现确实把未知费用变成 0。v2 ProviderResult 改为可空成本，缺失返回 MISSING_COST_MEASUREMENT；旧数字统计适配器显式拒绝 None，不补零。原始观测保留，完整门禁证据不足。尚未完成部分指标单独展示、配对覆盖率、来源模型和 HTML 缺测展示，故 R5 仅部分完成。

非法成本：bool、负值、字符串、NaN 原先被当缺失；Infinity 导致笼统内部错误。五个反例先失败，加入有限、非负、非 bool 数值检查后，均返回 target_cost_invalid。非法 Agent 终态另有反例，原先 worker_internal_error，现为 target_agent_observation_invalid，产物不包含合成私有原值。

兼容性发现：初版投影把 QA 自定义 trace schema 误当 Agent schema，回归产生 120 个 schema 错误。现在把 task_type 显式传到 provider，仅 Agent 走 Agent artifact 投影；普通 QA 保留原有轨迹解释，定向通过。

安全补充验收：HTTP 字节阈值恰好等于限制时接受，多一个字节拒绝；压缩响应在读取/解压前拒绝并关闭；缺 public_context 的旧 metadata 配置在 DNS 前阻断。target 53 项通过，包含原有 SSRF/peer/redirect 回归。

## 当前验证与剩余工作

第一轮全量单元测试为 **900 passed in 296.97s**，第二轮为 **914 passed in 240.95s**，分别对应当时启动的检查点。第二轮启动后又补了 QA 兼容性与 HTTP 边界测试，因此最后额外运行整个相关集合：`tests/unit/product_experiments tests/unit/scripts/test_product_experiment.py tests/unit/targets/test_http_rag.py`，**108 passed in 13.09s**。各集合重叠，不相加；不能把 914 写成最后补丁后再次完成的全量结果。

最后静态检查：mypy 198 个文件通过；ruff check 通过；ruff format --check 显示 582 files already formatted；git diff --check 通过。新增投影模块最初的同名变量类型冲突已经修复。没有运行本轮真实数据库/worker 故障集成，也没有远端 CI 结果。

迁移与使用说明：`docs/product-experiment-v2-migration.md`，列出新参数、退出码、metadata 迁移、费用语义、资源限制和未完成功能。当前结果 JSON/HTML 仍当私有调试产物，不直接公开真实业务内容。

S1 尚在收口；S2–S7 未完成。未提交、未推送，未同步教学/简历任务。后续必须完成费用/指标/正式资格、严格证据、持久执行、真实集成与精确 CI，不能把本阶段结果替代最终验收。

下一实施切片：先补 S1 退出码穷尽/中断、输入快照/单题预算和响应来源/耗时合同；再按 S2 升级版本化指标与任务适用性，清除仍存在的 legacy 默认值和硬编码资格信息。不要先把当前分支标成发布完成。S3–S7 仍按主方案顺序执行，教学/简历同步在实际证据收口后进行。
