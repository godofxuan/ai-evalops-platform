# 2026-09-15 独立审核修复与完整交付

## 结论与版本

本轮完成三包工程改进：锁后租约授权与锁序、版本化引用评分、发行证据与20×2合成故障演练。它提升的是任务结果及报告的可信度，不是模型质量、吞吐或生产资格。

- 唯一仓库：godofxuan/ai-evalops-platform。
- 固定基线：903ed7ca44e452faa93a62a9515f7fba733a8d1d。
- CODE_SHA：**bd10966fdc3a7abc094f8cf2b805cec84799f070**。
- 分支：codex/audit-remediation-20260915。DOC_SHA 在最终交付回执和 DELIVERY_MANIFEST.json 中给出；DOC 相对 CODE 只改文档，避免把文档哈希回写成自引用。
- 本文件落盘时未推送，CODE/DOC 的 GitHub CI 均为 NOT_RUN。已只读核对新远端分支不存在。若之后获准推送，必须以精确提交的实际 Actions 结果更新外部回执，不能借用历史成功。
- main、原工作区、旧基线工作区及 RAG 仓库未改；旧简历链接与旧证据保留。

## 实际修复

1. heartbeat、success、failure 在必要行锁取得后读取 PostgreSQL clock_timestamp，再核对 owner/version/status/expiry。reaper 先有限发现身份，按父→子锁序回收，持锁后重新核验。普通Run的claim/cancel反向锁还通过真实PG复现，包括 outbox 的隐式FK锁；使用非阻塞父级保护修复，未关掉并发。
2. 新 v3 执行统一引用来源ID解析：冲突、数值、空白拒绝，重复去重，额外/未解析引用进入precision分母；旧v2按旧规则重算。接线覆盖local、worker持久结果、报告、导出、离线重算，不更改历史成绩。
3. 固定BFCL源、数据与许可证进入必需release gate，缺料/篡改失败，不再以optional skip冒充发行验收。新增合成故障矩阵及四问报告、三入口README、可运行演示、完整简历答辩稿。
4. 整体验证发现的附带实际问题一并处理：Windows数据库事件循环与子进程兼容；artifacts误进入Docker构建上下文；旧README哈希与新文档版本混用。原旧README保存为精确快照，旧清单未改，当前README由新代码/交付身份绑定。

## 验证快照：不要把不同层级混算

| 验证 | 已取得的结果 | 限制 / 证据 |
| --- | --- | --- |
| CODE完整集成与并发 | **71 passed，3 skipped，273.73s** | code-integration-final.xml；3项需要真实MinIO |
| CODE完整非集成套件 | 1512 passed，1 failed，3 skipped，74 deselected | code-unit-final.xml；唯一失败是本收口文件尚未存在导致README链接缺失；此DOC补齐该文件 |
| DOC最终完整非集成套件 | 最终回执与 evidence/logs/doc-unit-final.xml 记录实际结果 | 不从CODE的失败运行推导DOC通过；没有该日志就不能宣称DOC全套通过 |
| 最终静态检查 | ruff、format、mypy通过；255个类型检查文件 | 不是业务质量指标 |
| 固定真实BFCL checker | **37 passed，0 skipped** | release-code.xml；两种篡改/缺料反向命令实际非零 |
| 20×2持久故障演练 | **40计划、24唯一接纳、12失败、4取消、39 attempts、39真实本地HTTP请求** | matrix-code/matrix-results.json；0模型调用；quality_status=EXECUTION_FAILED |
| 私有/公开离线验证 | PRIVATE_RECOMPUTED / PUBLIC_PROJECTION_ONLY | private-offline-code.log / public-offline-code.log；目标已关闭 |
| 本地QA/Agent演示 | 各120题固定样例DEMO_PASS；local完整重算一致 | demo-qa-code / demo-agent-code / demo-analysis-code；不是模型质量改善 |
| 旧报告兼容 | 原ZIP源码生成v2，再由新代码重算120题一致 | legacy-local-*；旧HTML与旧规则保留 |
| Cross Family原件 | **14666成员验证，两benchmark的四模型历史比较重算成功** | 原ZIP未修改；0新增推理 |
| 历史清单与评分卡 | 按原件/冻结边界验证，不抹掉NEGATIVE_SCALING | 历史README用c5dbeec精确快照；当前README不属于旧manifest覆盖范围 |

这些检查有重叠，不把次数相加当成独立样本量。调试失败和重跑全部保留，未挑最好一次报模型成绩。CODE与DOC的完整套件区别是明确的文档链接闭环，不是隐瞒失败。最终交付包必须同时包含DOC最终日志和回执才算本地交付验收结束。

### 最终矩阵的外部字节锚点

- 私有 report.json SHA-256：6732d3401438147f97f463a3bd3f2368c90797cba72537ba88a692a1762a55ec。
- 公开 report.json SHA-256：421ec9edce3892852b5a5bb8072d28557fec4b4c1583d2107a484406a95210fc。
- 实验 execution_id：1910b4db-ab90-4afb-8e70-6bb5a6bc77bd。
- report.result.evalops_sha 已断言为上面的完整CODE_SHA，result schema为3.0。
- 这是本轮本地公开合成材料的字节锚点，不是第三方来源签名或真实私有业务数据认证。

## 环境、权限与外部未验项

本地最终环境：Python3.12.13，项目uv.lock未改，专属.venv重新安装全部141个锁定包；PostgreSQL18.6 Windows便携实例、Redis8.8.1第三方Windows移植，均仅loopback且独立端口/测试库。它们不等价于CI的Linux镜像。环境摘要与原始安装日志入包；数据库文件、可执行运行时不入包。

明确未完成的外部验证：

- 本机没有Docker/可用MinIO；3项真实MinIO测试跳过，Linux Compose／MinIO整栈待CI或相应环境。
- 新分支尚无推送授权确认及精确CI；旧903ed的成功不能背书新实现。
- 3项Windows符号链接测试因1314权限跳过；未修改系统权限来假造通过。
- 未运行新吞吐性能实验、随机交错100轮、正式业务A/B、人评、Shadow或生产验收。历史NEGATIVE_SCALING保留。
- 未解决尚未复现的dispatcher token风险；未新增生产全量时序观测。当前锁/时间测试不是全局无死锁或分布式强实时证明。
- 用户本人掌握程度未知；必须亲自完成简历材料里的复现练习。

已停止功能扩张。不新增模型、框架、数据库产品、前端或部署；后续只应补上述明确验收条件，不默认再开功能项目。

## 从哪里读、怎么演示

- [锁序与新旧评分合同](CONTRACTS.md)：事务入口、非阻塞例外、版本分派和验证范围。
- [完整执行记录](EXECUTION_LOG.md)：为什么改、失败、原因与效果，含环境/工具问题。
- [验证索引](VALIDATION_INDEX.md)：按反例→修复→回归定位日志。
- [可运行演示](DEMO_GUIDE.md)：本地、持久故障演练、历史原件重算三路径。
- [完整简历与答辩](RESUME_AND_DEFENSE.md)、[同步建议](简历与教学同步建议.md)。
- 最终 ZIP：源码、变更patch、reviewed evidence、未修改原CrossFamily ZIP与清单；外部 DELIVERY_RECEIPT.json 记录DOC_SHA、ZIP摘要、最后测试及实际CI状态。

打包器会拒绝脏源码、CODE之后混入代码改动、运行时/数据库文件和非原始CrossFamily ZIP，逐成员复核摘要。哈希完整性不等于来源认证。
