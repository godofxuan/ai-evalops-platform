# Phase 0 逐步执行日志

## 记录格式

每一步至少说明：

- 目标：这一步要确认或改变什么；
- 判断：为什么此时做，是否符合当前阶段；
- 操作：修改内容或执行命令；
- 预期：操作前预期看到什么；
- 实际：未经美化的关键结果；
- 问题与处理：遇到什么、如何判断下一步；
- 效果与边界：这一步证明了什么、仍不能证明什么。

## P0-001 — 读取需求和检查空仓库

- 目标：确认当前只允许执行 Phase 0，并检查已有文件是否需要保留。
- 判断：这是所有修改前的必要只读检查，符合阶段顺序。
- 操作：以 UTF-8 读取用户提供的需求文件；列出工作区文件；运行 `git status --short --branch`。
- 预期：获得完整阶段合同和仓库基线。
- 实际：工作目录没有普通项目文件；`git status` 报告当前目录不是 Git 仓库。
- 问题与处理：第一次读取附件时，PowerShell 使用了错误默认编码，中文显示为乱码。随后显式使用 `Get-Content -Encoding utf8 -Raw` 重新读取。
- 效果与边界：确认可以从空目录初始化，且当前只执行 Phase 0；不能由此证明任何项目功能。

## P0-002 — 环境预检

- 目标：核实 Python、uv、Docker、Compose 和 Git 可用性。
- 判断：这些工具直接决定 Phase 0 哪些验收可以在本机真实执行。
- 操作：运行 Python launcher、`uv --version`、`docker --version`、`docker compose version` 和 `git --version`，并检查常见安装路径。
- 预期：最好能直接获得 Python 3.12、uv 和 Docker。
- 实际：
  - PATH 中 Python 为 3.13.5；
  - 另发现 Python 3.14 和 3.11；
  - 未发现 Python 3.12；
  - uv 不可用；
  - Docker 和 Compose 不可用；
  - Git 2.53.0 可用；
  - 全局 Git 用户名和邮箱未配置。
- 问题与处理：不把 3.13 当作 3.12 验证；计划使用 uv 管理项目 Python 3.12。Docker 缺失作为明确环境限制保留。
- 效果与边界：确定了真实工具基线；尚未证明 Python 3.12 依赖可安装或容器配置可运行。

## P0-003 — 第一次创建 uv 工具环境失败

- 目标：在工作区内安装 uv，避免修改全局 Python 环境。
- 判断：工具环境只用于开发引导，不属于产品依赖，并会加入 `.gitignore`。
- 操作：尝试 `py -3.13 -m venv .codex-tools`，随后准备使用该环境安装 uv。
- 预期：创建隔离工具环境。
- 实际：失败。Windows Python launcher 指向受保护的 Microsoft Store 路径，无法创建进程；后续环境内 Python 自然不存在。
- 问题与处理：改用已确认可直接访问的 Python 3.11 安装路径创建工具环境。uv 工具自身的宿主 Python 与项目目标 Python 是两个独立问题。
- 效果与边界：保留了一次真实的环境失败和根因判断；没有修改项目 Python 基线。

## P0-004 — uv 工具环境创建成功

- 目标：获得可用的 uv，并由它获取项目要求的 Python 3.12。
- 判断：使用本地 Python 3.11 只承载 uv，不运行项目。
- 操作：
  - `C:\Users\xuan\AppData\Local\Programs\Python\Python311\python.exe -m venv .codex-tools`
  - `.codex-tools\Scripts\python.exe -m pip install uv`
- 预期：在工作区隔离目录中安装 uv。
- 实际：成功安装 uv 0.11.32。
- 问题与处理：pip 只提示自身有新版本；这不影响 uv，因此不做无关升级。
- 效果与边界：uv 命令现在可由 `.codex-tools\Scripts\uv.exe` 使用；尚未创建项目环境或锁文件。

## P0-005 — 初始化 Git

- 目标：开始保留可审计变更和小提交。
- 判断：用户要求每阶段创建提交，空目录必须先初始化仓库。
- 操作：`git init -b main`。
- 预期：创建 main 分支的空 Git 仓库。
- 实际：Git 仓库初始化成功。
- 问题与处理：全局 Git 身份尚未配置；提交时不会擅自写入用户全局配置，将使用仅对单次提交生效并明确记录的自动化身份。
- 效果与边界：后续差异和提交可追踪；当前仍没有基线 commit。

## P0-006 — 固化范围、架构和记录规范

- 目标：把聊天中的执行要求变成仓库内可持续维护的合同。
- 判断：先写合同再写测试和实现，符合用户指定的阶段顺序。
- 操作：新增范围、架构、工程日志、逐步执行日志以及 Git 文本/忽略规则。
- 预期：后续每个变更都可以对照验收标准并留下证据。
- 实际：本条随文件创建完成。
- 问题与处理：无。
- 效果与边界：规则已经持久化；它本身不证明应用行为。

## P0-007 — 冻结写测试前的文件计划

- 目标：满足“先列出将新增或修改的文件，再写测试”的阶段要求。
- 判断：文件计划必须覆盖 Phase 0 验收，但不能预建后续领域模块。
- 操作：在 `docs/00_project_scope.md` 增加计划文件树。
- 预期：测试和实现都能映射到已声明的阶段目标。
- 实际：计划覆盖应用入口、健康检查、依赖客户端、迁移、测试、容器、CI 和文档。
- 问题与处理：原建议目录把 Reaper 放在 `app/jobs/reaper.py`，但该文件属于用户必须亲自实现的后续学习模块，因此 Phase 0 改用通用 `app/cli.py` 进程骨架。
- 效果与边界：避免提前侵入用户学习模块；实施中若需要新文件，仍必须补记原因。

## P0-008 — 获取 Python 3.12 并完成首个 RED

- 目标：建立与项目声明一致的运行环境，并证明 liveness 测试会因功能缺失而失败。
- 判断：不能用本机默认 Python 3.13 代替目标 3.12；首个测试只验证一条 HTTP 公共行为。
- 操作：
  - 让 uv 0.11.32 下载并安装工作区隔离的 CPython 3.12；
  - 创建 `.python-version`、`pyproject.toml` 和 `tests/api/test_health.py`；
  - 运行 `uv lock`、`uv sync --locked --all-groups`；
  - 运行 `uv run --no-sync pytest tests/api/test_health.py -q`。
- 预期：依赖安装成功，测试因 `app.main` 尚不存在而失败。
- 实际：
  - 安装 CPython 3.12.13；
  - 锁定 47 个包并安装 45 个包；
  - pytest 收集失败：`ModuleNotFoundError: No module named 'app'`；
  - 同时出现 Starlette 的旧 `TestClient`/`httpx` 弃用警告。
- 问题与处理：失败原因与缺失功能一致，RED 有效。为避免新项目从第一天携带弃用警告，把测试客户端改为 `httpx.AsyncClient + ASGITransport`；测试的 URL、状态码和响应断言不变。
- 效果与边界：证明测试能检测 liveness 功能缺失；尚未证明实现正确。

## P0-009 — Liveness 最小 GREEN 实现

- 目标：只实现让第一条公开行为成立所需的最小代码。
- 判断：使用独立 health router 是 FastAPI 的自然公共边界；当前不加入 readiness 或外部资源。
- 操作：
  - 创建 `app/main.py` 的 app factory；
  - 创建 `app/api/routes_health.py` 的 `GET /health/live`；
  - 使用 Pydantic 响应模型固定 `{"status": "alive"}` 合同。
- 预期：修改后的 ASGI 测试通过且无旧 `TestClient` 警告。
- 实际：第一次验证仍在收集阶段报告 `ModuleNotFoundError: app`，即使 `app/` 已存在。
- 问题与处理：确认这是 Windows 下 pytest console entry point 未把仓库根目录加入导入路径。给 pytest 增加显式 `pythonpath = ["."]`；没有修改测试断言或应用行为。
- 效果与边界：修正后目标测试 `1 passed`。实现只声明 API 进程可响应，不表示 PostgreSQL、Redis 或迁移已就绪。

## P0-010 — Readiness 全部健康场景 RED

- 目标：定义 `/health/ready` 的成功响应，包括四个必需依赖。
- 判断：先用注入 probe 隔离 HTTP 合同，再用真实服务集成测试验证具体探测器；两者证明的问题不同。
- 操作：新增 API 测试，注入固定返回 PostgreSQL、Redis、artifact 和 migration 全部健康的 probe。
- 预期：测试因 readiness 公共类型和 app factory 参数尚不存在而失败。
- 实际：pytest 收集失败：`ModuleNotFoundError: No module named 'app.health'`。
- 问题与处理：失败与缺失 readiness 接口一致，RED 有效；实现最小公开类型、probe 协议、路由和 app factory 注入点。
- 效果与边界：实现后目标文件 `2 passed`。测试只定义 HTTP 合同，不会假装真实依赖已连接。

## P0-011 — 配置加载与秘密脱敏 RED

- 目标：定义环境变量配置合同，并防止数据库/Redis URL 出现在配置对象 repr 中。
- 判断：真实 readiness 依赖安全配置，因此配置应先于客户端和探测器实现。
- 操作：新增单元测试，设置 `EVALOPS_DATABASE_URL`、`EVALOPS_REDIS_URL` 和 `EVALOPS_ARTIFACT_ROOT`。
- 预期：测试因 `app.core.config` 不存在而失败。
- 实际：pytest 收集失败：`ModuleNotFoundError: No module named 'app.core'`。
- 问题与处理：失败与配置模块缺失一致，RED 有效；使用 Pydantic Settings 和 `SecretStr` 实现最小合同。
- 效果与边界：实现后测试 `1 passed`，但 pytest 同时报告用户全局临时目录旧文件的权限清理警告。该测试只证明配置加载和对象表示脱敏，不证明日志全链路脱敏。

## P0-012 — 隔离 pytest 临时目录

- 目标：消除与本项目无关的全局临时目录权限噪声。
- 判断：警告来自 pytest 清理用户临时目录中的既有残留，不应删除不属于本项目的文件。
- 操作：把 `--basetemp` 固定为仓库内 `.pytest-tmp`，并加入 `.gitignore`。
- 预期：后续 pytest 不再扫描或清理该外部残留。
- 实际：待下一次测试确认。
- 问题与处理：无项目文件被删除。
- 效果与边界：只改善测试隔离，不改变应用行为。

## P0-013 — Readiness 异常脱敏 RED

- 目标：依赖异常不能通过 readiness 响应泄露连接串或密码。
- 判断：组合 probe 应把底层异常映射为稳定错误码；日志可保留异常类型，但响应不能保留原始文本。
- 操作：新增单元测试，其中 PostgreSQL 检查抛出含秘密 URL 的异常。
- 预期：测试因 `CompositeReadinessProbe` 尚不存在而失败。
- 实际：pytest 收集失败：无法从 `app.health.service` 导入 `CompositeReadinessProbe`。
- 问题与处理：失败与缺失组合 probe 一致，RED 有效；实现并发检查、单项超时和稳定错误码映射，且不把异常文本放入模型。
- 效果与边界：实现后测试 `1 passed`，且 P0-012 的外部临时目录警告消失。该测试验证聚合和响应模型，不替代真实服务连接测试。

## P0-014 — Artifact 目录真实写入探测 RED

- 目标：readiness 应证明 artifact 目录真实可写，并且探测后不留临时文件。
- 判断：`os.access` 在 ACL、容器挂载和竞争条件下只能提供提示；一次最小真实写入更接近应用所需能力。
- 操作：新增异步测试，调用公开探测函数后断言目录仍为空。
- 预期：测试因 `check_artifact_directory` 不存在而失败。
- 实际：pytest 收集失败：无法导入 `check_artifact_directory`。
- 问题与处理：失败与缺失探测函数一致，RED 有效；使用后台线程执行临时文件写入、flush、`fsync` 和 finally 清理，避免阻塞事件循环。
- 效果与边界：实现后 readiness 单元测试 `2 passed`。只验证目录写入能力，不实现后续 content-addressed artifact 存储。

## P0-015 — 结构化日志递归脱敏 RED

- 目标：日志保持 JSON 可解析，同时屏蔽顶层和嵌套敏感字段。
- 判断：配置对象的 `SecretStr` 不能保护调用者主动传入日志的值，日志处理链还需要统一兜底。
- 操作：新增测试，写入 API Key、数据库 URL、嵌套 Authorization 和普通 outcome。
- 预期：测试因 `app.core.logging` 不存在而失败。
- 实际：pytest 收集失败：`ModuleNotFoundError: app.core.logging`。
- 问题与处理：失败与日志模块缺失一致，RED 有效；实现 structlog + 标准库 logging 处理链，在 JSON 渲染前递归按敏感字段名脱敏。
- 效果与边界：实现后日志测试 `1 passed`。测试验证按字段名脱敏；不能识别被误放进普通字段的任意秘密文本。

## P0-016 — Request ID 响应合同 RED

- 目标：没有上游 request ID 时，由服务端生成可用于日志关联的 UUID。
- 判断：request ID 是跨阶段通用基础，且只建立关联标识，不涉及身份认证或租户边界。
- 操作：新增 HTTP 测试，读取 `X-Request-ID` 并按 UUID 解析。
- 预期：当前响应没有该 header，测试以缺少键失败。
- 实际：2 条既有测试通过，新测试以 `KeyError: x-request-id` 失败。
- 问题与处理：RED 与缺失中间件一致；实现纯 ASGI 中间件，生成或接受受长度/字符限制的 request ID，绑定日志上下文，记录路径、状态和耗时并写入响应头。
- 效果与边界：实现后健康 API 测试 `3 passed`。只证明响应关联 ID，不等同于 OpenTelemetry trace。

## P0-017 — 真实基础设施 readiness 集成合同 RED

- 目标：定义使用真实 PostgreSQL、Redis、artifact 目录和 Alembic revision 的端到端 readiness 验收。
- 判断：SQLite 或 fake client 都不能替代此测试；本机无 Docker 时必须跳过并如实记录，CI 将提供真实服务。
- 操作：
  - 新增 `tests/integration/test_readiness.py`；
  - 只有显式设置 `EVALOPS_RUN_INTEGRATION=1` 才连接外部服务；
  - 在写实现前运行测试，确认基础设施工厂缺失。
- 预期：当前因 `build_infrastructure_readiness_probe` 或 persistence 模块不存在而收集失败。
- 实际：pytest 收集失败：无法从 `app.health.service` 导入 `build_infrastructure_readiness_probe`。
- 问题与处理：
  - RED 与缺失基础设施工厂一致；
  - 实现 PostgreSQL `SELECT 1`、Redis `PING`、artifact 写入和 Alembic current/head 比较；
  - 文件计划新增 `app/persistence/redis.py`，让 PostgreSQL 和 Redis 客户端同处基础设施边界，而不是提前创建 Phase 6 事件代码；
  - FastAPI lifespan 负责创建/关闭客户端，测试注入 probe 时不打开真实连接。
- 效果与边界：实现后本机结果为 `1 skipped`，原因是未设置真实服务开关。该合同在真实服务中可证明连接和迁移就绪；本机跳过时不能声称通过。

## P0-018 — Worker/Reaper 生命周期入口 RED

- 目标：为 Compose 中的非 API 进程建立可执行入口，同时明确它们没有任务业务能力。
- 判断：Phase 0 需要多进程骨架，但不能提前实现用户后续要亲自学习的领取或 Reaper 逻辑。
- 操作：新增 CLI 测试，调用 `worker --check`，要求 JSON 日志标记 `capability=lifecycle_only`。
- 预期：测试因 `app.cli` 不存在而失败。
- 实际：pytest 收集失败：`ModuleNotFoundError: app.cli`。
- 问题与处理：RED 与缺失入口一致；实现 `worker|reaper` 两个角色、`--check` 模式、结构化日志和停止信号等待，不访问任何 Job 或领域表。
- 效果与边界：实现后 CLI 测试 `1 passed`。入口成功只证明配置/进程骨架可调用，不证明 Worker 能领取任务。

## P0-019 — Readiness 503 回归合同

- 目标：确认组合结果为 `not_ready` 时，HTTP 状态码是 503，并且响应只含稳定错误码。
- 判断：503 分支是在 P0-010 最小路由实现中与成功分支同时加入的，因此此处无法诚实制造 RED；补充测试用于锁定已有行为。
- 操作：注入固定失败 probe 并断言状态码和完整 JSON。
- 预期：首次运行即通过；若失败则说明先前实现没有满足完整 readiness 合同。
- 实际：首次运行通过，健康 API 测试共 `4 passed`。
- 问题与处理：这不是新的 RED→GREEN 周期，作为回归合同单独记录。
- 效果与边界：只验证 HTTP 映射，底层异常脱敏由 P0-013 验证。

## P0-020 — Docker、Compose、CI 与 README 骨架

- 目标：让同一锁文件和代码可以在本地、容器和 CI 中使用，并给学习者提供诚实的启动/限制说明。
- 判断：
  - 应固定 Python、uv、PostgreSQL 和 Redis 的具体版本；
  - Compose 必须等待依赖 healthcheck，不把“容器进程已启动”当成“依赖已就绪”；
  - CI 的真实服务集成测试与完整 Compose smoke 是不同证据，均保留；
  - README 必须区分已实现、未来目标和不能证明的内容。
- 操作：
  - 新增 Dockerfile、`.dockerignore`、`deploy/compose.yaml`；
  - 新增 GitHub Actions：格式、lint、类型、无外部依赖测试、真实服务迁移/集成、镜像构建、Compose smoke；
  - 新增 README 的业务、架构、启动、健康、配置、测试、未来领域、限制和面试路径。
- 预期：静态格式可解析；在有 Docker 的环境中镜像和完整拓扑可运行。
- 实际：待本地静态/动态验证。
- 问题与处理：本机预检已知没有 Docker，因此预计 Docker 命令会失败为“命令不存在”；不会据此改用不等价的模拟。
- 效果与边界：文件存在不等于镜像或 Compose 已运行，必须以后续命令证据为准。

## P0-021 — 第一轮静态质量检查失败与修正

- 目标：在全量测试前发现格式、lint 和类型问题。
- 判断：先运行只读检查，不能直接自动修复后假装从未失败。
- 操作：运行锁文件检查、`ruff format --check .`、`ruff check .` 和 `mypy app`。
- 预期：锁文件应通过；初次实现可能暴露机械质量问题。
- 实际：
  - `uv lock --check` 通过，解析 47 个包；
  - format 报告 13 个文件需要格式化；
  - lint 报告 3 个导入顺序问题和 2 个 async 函数直接使用 `pathlib`；
  - mypy 报告 1 个 Redis `ping()` 的 `Awaitable[bool] | bool` 联合类型问题。
- 问题与处理：
  - 使用 Ruff 处理纯机械格式和导入；
  - 把集成测试的项目根路径移到模块加载阶段；
  - 把异步测试中的目录枚举放入 `asyncio.to_thread`；
  - 对 redis-py 已知的异步客户端返回类型显式 `cast(Awaitable[bool], ...)`，仍然真实 await；
  - 不关闭 ASYNC 或 mypy 规则。
- 复查中间结果：
  - Ruff 自动修复 3 个导入并格式化 13 个文件；
  - format 通过；
  - mypy 通过；
  - lint 仍指出 `tmp_path.iterdir()` 虽作为 `to_thread` 参数，但调用表达式仍位于 async 函数。
- 二次处理：提取同步 `_list_directory` helper，再由 `asyncio.to_thread` 调用；没有忽略规则。
- 最终复查：锁文件通过；27 个文件格式通过；lint 全部通过；mypy 检查 14 个应用文件无问题。
- 效果与边界：这些修改提高静态一致性，不改变 readiness 的外部合同。

## P0-022 — 首次完整回归的测试模块名冲突

- 目标：一次收集并运行全部测试，发现单文件目标测试无法暴露的交互问题。
- 判断：目标测试通过后仍必须运行相关回归，不能把多个单文件结果拼成“全量通过”。
- 操作：运行不带文件过滤的 `pytest`，随后继续执行 Alembic/YAML/CLI 独立检查。
- 预期：9 条非集成测试通过，1 条集成测试因无真实服务跳过。
- 实际：
  - pytest 在收集阶段失败；
  - `tests/integration/test_readiness.py` 和 `tests/unit/test_readiness.py` 被默认导入模式映射为同一个顶层模块 `test_readiness`；
  - Alembic 报告 `20260728_0001 (head)`，offline upgrade SQL 成功生成；
  - Compose 和 CI YAML 均成功解析；
  - Worker/Reaper `--check` 均返回 JSON 和 `lifecycle_only`。
- 问题与处理：pytest 增加 `--import-mode=importlib`，按路径隔离同名测试模块；没有删除测试或改名掩盖结构问题。
- 效果与边界：解决测试收集冲突后仍需重跑全量；Alembic offline SQL 只证明脚本可生成，不证明真实 PostgreSQL 已应用。

## P0-023 — 完整回归与独立 Uvicorn smoke

- 目标：证明所有测试可以一次收集，并确认 API 能由真实 Uvicorn 进程服务。
- 判断：ASGITransport 快速且稳定，但不能单独证明 Uvicorn 启动路径；两类验证都需要。
- 操作：
  - 重跑无过滤 `pytest`；
  - 使用 `.venv` 的 Python 启动 Uvicorn 到 `127.0.0.1:8765`；
  - 分别请求 liveness 和 readiness；
  - 尝试 Ctrl+C 停止进程。
- 预期：
  - 9 条本地测试通过、1 条真实服务集成跳过；
  - liveness 200；
  - 因本机无 PostgreSQL/Redis，readiness 503；
  - Ctrl+C 正常停止。
- 实际：
  - `10 collected / 9 passed / 1 skipped`；
  - liveness HTTP 200，JSON `{"status":"alive"}`，响应含 UUID request ID；
  - readiness HTTP 503：artifact ok，PostgreSQL unavailable，Redis timeout，migration unavailable；
  - 响应没有连接 URL 或密码；
  - Uvicorn PTY 连续三次 Ctrl+C 都未退出。
- 问题与处理：从启动日志精确确认本次测试进程 PID 70304，只终止该进程；随后轮询会话确认退出码 1。没有按名称批量终止 Python。
- 效果与边界：证明真实 HTTP 启动/响应路径；不能证明依赖健康场景或优雅 SIGTERM 行为。

## P0-024 — 本机 Docker 验收失败

- 目标：实际执行 Dockerfile/Compose 验收，不只依赖预检推断。
- 判断：Docker build 和 Compose 是不可由 YAML parser 等价替代的动态证据。
- 操作：
  - `docker compose -f deploy/compose.yaml config`
  - `docker build --tag ai-evalops-platform:phase0 .`
- 预期：预检已知 `docker` 不存在，两条命令会在启动前失败。
- 实际：两条命令都由 PowerShell 报 `CommandNotFoundException: docker`。
- 问题与处理：没有安装 Docker Desktop，因为它涉及系统级 GUI/虚拟化变更；CI 增加完整 Compose smoke，等待未来在具备 Docker 的环境执行。
- 效果与边界：确认本机无法动态验收；之前的 YAML parse 仍只算静态证据。

## P0-025 — 小提交与 Git 环境问题

- 目标：按合同创建可审计的小提交，且每次提交前检查 whitespace。
- 判断：设计合同、工具链、RED 测试、实现、容器/CI、最终文档应分离。
- 操作：选择性 stage，运行 cached diff check，使用单次 `Codex <codex@localhost>` 身份提交。
- 实际问题与处理：
  1. 第一次 cached diff check 报两个末尾空行，但 PowerShell 继续执行并创建根提交；清理后，在未 push 前 amend 为 `dddb98b`，后续命令在检查非零时显式 exit。
  2. sandbox 创建的 `.git` 属于 `CodexSandboxOffline`，当前命令用户是 `xuan`，Git 报 dubious ownership；没有改全局配置，改用每条命令的 `-c safe.directory=...`。
  3. `.python-version` 被初始 ignore 规则排除；移除该规则后提交 Python 3.12 pin。
  4. 多个 staged check 找到末尾空行；全部在相应提交前修复。
  5. 一度准备把 30 个文件放入一个提交；只撤销 staged 状态并拆成 tooling、tests、implementation 三个提交，工作区内容没有丢失。
- 已创建提交：
  - `dddb98b docs: define phase 0 engineering contract`
  - `8523094 chore: initialize project tooling`
  - `2a51a30 test(health): define phase 0 runtime contracts`
  - `8cf1b3e feat(health): implement phase 0 runtime foundation`
  - `17c9726 chore: add container and ci foundation`
- 效果与边界：TDD 顺序可以从 Git 历史看到；未 push。

## P0-026 — Phase 0 最终结论

- 目标：更新 README 和工程日志，明确实际证据、限制、学习重点和 Phase 1 建议。
- 判断：只有在代码/测试/静态检查/smoke/提交完成后，才能把阶段标记为完成。
- 操作：
  - 把 `docs/engineering_journal.md` 从“进行中”更新为“完成”；
  - 回填实际文件、失败、验证、未解决问题、替代方案、面试追问；
  - README 加入本机实测表；
  - 最后运行 whitespace、状态和 Git 历史检查。
- 预期：只剩 README/日志待提交；提交后工作区干净。
- 实际：
  - 最终 cached diff whitespace 检查通过；
  - `uv lock --check` 通过，47 个包；
  - Ruff format 检查 27 个文件通过；
  - Ruff lint 全部通过；
  - mypy 检查 14 个应用文件通过；
  - pytest 再次得到 `9 passed, 1 skipped`；
  - 提交后 `git status --short` 无输出；
  - 最终文档提交在 amend 前为 `7df0460`，amend 后以最新 `git log` 为准。
- 问题与处理：无新增代码问题；最后只回填本条实际结果并 amend 未 push 的最新文档提交。
- 效果与边界：Phase 0 的本机可执行证据和环境限制已闭环；停止，不开始 Phase 1。

## Phase 1 建议（未开始）

下一阶段先定义 API Key → tenant principal 的服务端身份边界，再实现 dataset 元信息、immutable dataset version 和本地 content-addressed artifact。建议继续采用以下顺序：

1. 先写 API Key 只显示一次、数据库不保存明文、撤销/过期的合同；
2. 再写所有 dataset 查询必须从 principal 取得 tenant 的越权 RED 测试；
3. 为 JSONL 上传定义大小、行数、格式、重复 case ID 和失败无半成品合同；
4. 最后实现原子 artifact 写入与 dataset version 事务。

不要在 Phase 1 提前创建 Run/Job、幂等或 Worker 领取逻辑。
