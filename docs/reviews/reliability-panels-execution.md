# 2026-09-12 重复运行可靠性：实施与学习记录

本轮在独立 `codex/reliability-panels-v1` 分支，从已交付 DOC `6be5f971cc6b6d53d02bd026cf27473bc77785cc` 开始。对应运行 CODE `c5dbeecaf5d06ba2bbae7f7bcb4b7a7678911997`；未从最新 main 开始，未修改原工作区和 RAG。

## 选择与范围

此前离线研究证明同样的平均分可能隐藏不同逐题稳定性。本轮把原型推进为可恢复客户端和可重算报告，而非新建数据库模型或扩展 Agent 框架。每个 trial 复用现有完整 durable paired experiment，原质量门禁、worker lease/fencing、accepted attempt 规则不变。

独立审查提出并已纳入的边界：默认重试存在，因此只能称固定重试策略的执行结果；实际组件仅跨trial一致而非预先认证；增加 panel UUID 防止同参数新面板意外复用旧键；跨trial去重包括 result_id；不把 PRIVATE_RECOMPUTED 当来源认证、时间戳或采样独立性证明。

## 已进行的修改

| 内容 | 为什么这样做 | 效果与验证位置 |
|---|---|---|
| reliability.py | 固定计划、trial范围、题集/代码/租户绑定；仅从私有重算证据读取 | task success面板、缺失/未知/失败/取消、成本与重试范围；test_reliability.py |
| reliability_client.py | 执行前保存计划；每trial固定幂等键与receipt，拒绝覆盖和链接路径 | submit恢复、collect只导出终态；离线report/verify重建；客户端测试 |
| product_reliability.py | 提供实际可运行入口，避免用户手拼聚合JSON | plan/submit/collect/report/verify；凭据只读环境变量；CLI测试 |
| product_reliability_support.py | 单元fixture不能替代真实worker与持久化 | 接入既有QA/Agent集成，覆盖重试、取消、失败、身份隔离及复算；需真实服务 |
| product_ci_evidence.py | 如果CI执行新阶段，应保留可复核结果但不泄露原文 | 新增严格白名单阶段字符串；脱敏单元回归 |
| reliability-panels.md | 用户需要知道怎么跑、哪些数字不能夸大 | 完整命令、指标解释、私有数据和验收边界 |

## 问题、修正及实际环境

1. Windows Git ownership 检查：仅对精确仓库传命令级 safe.directory；没有更改全局信任列表。旧 worktree 和主分支未切换。
2. 新 worktree 尝试两次离线 locked sync，分别缺 numpy 与 inspect-ai 缓存，未下载依赖、未改变锁文件。这是环境准备未完成，不能称新环境验收通过。随后对旧收口工作区的既有 Python 3.12.13 环境执行 `uv sync --locked --all-groups --dry-run --offline`：核对 141 installed packages，输出 Would make no changes。后续测试使用该已核对环境，在新 worktree 中导入新源码；旧 .venv 未被修改。
3. 首轮静态检查暴露汇总字典类型推断、测试租户字段假设与循环变量捕获问题。显式标注字典类型；从真实鉴权私有报告读取tenant，而非假设公开RunRead提供tenant_id；transport初始化固定故障模式。另补回自动清理后需要的UUID导入。核心与集成辅助模块mypy后续通过。
4. 新单元测试搭建首次两个失败：QA的派生citation指标不能直接作为注册evaluator名字；HTML测试需完整报告结构。改为真实worker evaluator_names与完整报告，再注入反例，不放松产品断言。核心测试32 passed。
5. 首轮新客户端fixture忘记重算变更后的input_snapshot hash，正确触发证据完整性拒绝。修复测试构造顺序，不修改验证器。第一次全量运行启动时测试尚在补齐，保留其失败结果，再对稳定版本完整运行。
6. 恢复性审查发现 x模式锁文件会在进程被kill后留下死锁。新客户端使用OS advisory锁并加入实际子进程kill恢复测试；旧bundle writer只在临时stage使用，避免旧export.lock阻塞正式trial目录。常驻锁文件不包含私有内容，不用删除锁文件作为恢复手段。
7. 客户端回归发现新HTML renderer依赖字典插入顺序，而文件编码会排序键，导致正常保存后verify失败。修复在renderer本身固定JSON键顺序，增加JSON roundtrip渲染不变断言；不在客户端绕过HTML检查。随后核心+客户端+CLI合并集合49 passed。
8. 首次全量实际为1252 passed / 1 skipped / 40 deselected / 10 fixture errors，250.55秒。10个errors均来自运行启动时捕获的旧测试fixture遗漏input_snapshot重hash；保留full-unit.xml。Windows唯一symlink skip为权限1314。之后对稳定版本重新执行，不把该轮写成全绿。
9. 一次全项目mypy命令显式再添加已被integration导入的helper，导致重复module名称；按现有CI入口重跑，229源码文件通过。历史证据清单另外拒绝README大小变化，因README是已冻结制品。撤销本轮新增导航段，保留原README与历史hash；新增教程独立交付。清单复验通过，没有更新历史摘要去掩盖修改。
10. 新客户端真实process kill测试在Windows selector事件循环下不支持asyncio子进程接口，改用to_thread(Popen)运行并硬杀实际进程；不是测试桩件。17项客户端/CLI回归通过。进程硬杀可能留下ledger外私有stage文件，已在教程披露，不自动删除未知文件。

## 检查记录与待验收边界

- 核心+既有durable报告/验证针对集合：58 passed；输出 `artifacts/reliability-checks/focused.xml`。
- 首次全量、最终全量、客户端恢复、格式/类型/证据检查结果由完成时追加；不同集合有重叠，不能相加。
- 本机只读检查未找到Docker/PostgreSQL安装或5432/6379监听。真实数据库集成尚未在本机执行；缺环境不计通过。
- 当前开发中分支没有新发布 CODE/DOC 身份或对应新CI。历史绿色CI不背书本次改动。远端写入需用户确认；不会推main或自动合并。

停止边界：完成本轮本地实现和可运行测试后，不自动开始轨迹匹配、语义judge、人评或付费模型试验。真正的“第一阶段完整验收”还要求新增真实持久化集成在精确代码CI通过；记录状态必须保留该差异。

## 本轮本地交付结果

- 最终全量非集成：**1268 passed / 1 skipped / 40 deselected**，214.88秒，日志 `artifacts/reliability-checks/final-unit.xml`。唯一skip仍是Windows权限1314导致旧symlink测试不能执行；40项集成未运行，不能相加为通过。对比基线1218个本机通过项，本轮新增50个通过项（32核心、17客户端/CLI、1CI脱敏）。
- 单独执行真实持久产品集成入口：**1 skipped**，明确需要隔离迁移过的PostgreSQL。记录 `integration-local.xml`，不是绿色验收。
- Ruff格式：661 files already formatted；lint通过；Mypy按CI同入口检查229源码文件通过。历史证据manifest与project_scorecard通过；原NEGATIVE_SCALING和quality INPUT_BLOCKED结论不变。
- 保留合成端到端客户端夹具1 passed / 3.86秒；据该原始私有ledger实际执行新CLI report与verify，输出COMPLETE_DESCRIPTIVE_PANEL、PRIVATE_RECOMPUTED_PANEL、server_provenance_verified=false。数据与服务端身份均是明确的合成fixture，不是部署SHA、真实模型采样或性能成绩。
- 首次失败全量、最终全量、针对测试、集成skip、演示JUnit分开保留。报告顺序错误与锁恢复问题已修复，未修改旧质量分数或历史文件摘要。
- 最后只读检查：原主工作区及原收口worktree Git status均为空；专用功能worktree有本轮12个待提交文件。没有新提交，没有推送，没有新CI；等待用户确认后才能推送专用分支运行现有CI，不推main、不合并。

当前结论：**LOCAL_IMPLEMENTED_CI_PENDING**。功能代码、客户端、说明和本地测试已完成；完整第一阶段验收尚缺精确新代码的真实数据库CI。没有默认进入第二阶段。
