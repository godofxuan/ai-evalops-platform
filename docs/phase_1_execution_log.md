# Phase 1 逐步执行日志

## 记录格式

每一步记录目标、适配性判断、操作、预期、实际、问题与处理、效果与边界。RED、skip、未运行和环境失败不得删除或改写成通过。

## P1-001 — 用户确认与仓库预检

- 日期：2026-07-29
- 起始 SHA：`f574cbe3c3836fc91188de1a52392ced9cc89924`
- 目标：确认用户已批准 Phase 1，并检查 Phase 0 结果是否可作为干净基线。
- 判断：用户发送“继续”，而 Phase 0 最终明确等待 Phase 1 确认，因此这是进入下一阶段的充分授权；不授权 Phase 2。
- 操作：重读 TDD 技能；检查 Git status、起始 SHA、文件、Python、uv、Docker、Compose 和本地 PostgreSQL/Redis 服务。
- 预期：工作区干净，Python/uv 可用；Docker 和真实服务可能仍不可用。
- 实际：
  - `main` 工作区干净；
  - 起始 SHA 与 Phase 0 最终提交一致；
  - CPython 3.12.13 和 uv 0.11.32 可用；
  - Docker/Compose 命令不存在；
  - 未发现本地 PostgreSQL/Redis service。
- 问题与处理：真实数据库验证仍不能在本机执行；继续保留 integration marker 和 CI 动态验证，不引入 SQLite。
- 效果与边界：确认可以安全修改；尚未证明 Phase 1 任何行为。

## P1-002 — 核对当前官方接口

- 目标：避免使用过时的上传、事务和密码派生接口。
- 判断：FastAPI、SQLAlchemy 和安全接口会演进，实施前应以官方文档确认。
- 操作：查阅 FastAPI `UploadFile`/multipart、SQLAlchemy async session/`with_for_update`、Python 3.12 `hashlib.scrypt` 和 `hmac.compare_digest` 文档。
- 实际：
  - FastAPI 文件上传使用 multipart form，需 `UploadFile`；
  - SQLAlchemy async API 支持 async sessionmaker 和 `with_for_update`；
  - Python 3.12 提供带 salt、可调 n/r/p 的 scrypt；
  - 常量时间 digest 比较使用 `hmac.compare_digest`。
- 问题与处理：multipart 需要显式项目依赖 `python-multipart`，加入文件计划和锁文件。
- 效果与边界：确认接口选择；文档本身不证明实现安全。

## P1-003 — 冻结问题、设计合同和文件计划

- 目标：在测试和实现前固定 Phase 1 的公开语义与改动范围。
- 判断：身份、租户、文件系统和数据库事务相互影响，必须先明确失败语义和阶段边界。
- 操作：新增 `docs/02_domain_model.md`、`docs/08_security_boundaries.md` 和本日志；更新工程日志为 Phase 1 进行中。
- 预期：后续每个 RED→GREEN 都能映射到明确合同。
- 实际：设计合同包含 API Key、tenant、HTTP、JSONL、artifact、事务、替代方案和限制。
- 问题与处理：无。
- 效果与边界：合同已持久化，但不证明代码存在。

## 计划文件

实施中如新增或取消文件，必须在日志说明。

```text
修改
  .env.example
  README.md
  alembic/env.py
  app/core/config.py
  app/domain/__init__.py
  app/domain/enums.py
  app/main.py
  app/persistence/database.py
  docs/engineering_journal.md
  pyproject.toml
  uv.lock

新增
  alembic/versions/20260729_0002_identity_datasets.py
  app/api/dependencies.py
  app/api/errors.py
  app/api/routes_datasets.py
  app/artifacts/__init__.py
  app/artifacts/storage.py
  app/auth/__init__.py
  app/auth/api_keys.py
  app/auth/dependencies.py
  app/auth/principals.py
  app/auth/service.py
  app/datasets/__init__.py
  app/datasets/schemas.py
  app/datasets/service.py
  app/datasets/validation.py
  app/persistence/orm_models.py
  docs/02_domain_model.md
  docs/08_security_boundaries.md
  docs/phase_1_execution_log.md
  scripts/create_dev_api_key.py
  scripts/revoke_api_key.py
  tests/api/test_datasets.py
  tests/integration/test_identity_and_datasets.py
  tests/unit/artifacts/test_storage.py
  tests/unit/auth/test_api_keys.py
  tests/unit/datasets/test_validation.py
  tests/unit/persistence/test_orm_models.py
```

## Phase 1 验收标准

1. API Key 生成后只显示一次，ORM/数据库不保存明文。
2. scrypt hash 有随机 salt，错误 key 验证失败，digest 使用常量时间比较。
3. revoked、expired 和 inactive tenant 不能认证。
4. unknown prefix 走 dummy hash 路径，对外错误一致。
5. 请求体 `tenant_id` 被拒绝；tenant 只能来自 principal。
6. 跨 tenant dataset/version 访问返回 404。
7. Dataset create/get API 合同通过。
8. JSONL 大小、行数、单行、UTF-8、JSON、字段和重复 case ID 约束通过。
9. 相同 dataset 不允许重复 SHA version。
10. Artifact path 只由 SHA-256 生成，临时文件失败后清理，相同内容物理去重。
11. Alembic migration 定义所有 Phase 1 表、外键、唯一约束和索引。
12. 真实 PostgreSQL integration contract 存在；只有真实服务运行结果才算动态通过。
13. Ruff、mypy、非集成测试和可执行 API smoke 通过。
14. Docker/Compose 若本机仍不可用，保留实际失败，不声称通过。
15. 创建多个小提交，不 push，完成后停止。

## P1-004 — API Key 生成与哈希 RED

- 目标：定义“明文只交付一次、存储哈希可验证、对象 repr 不泄露”的最小公开行为。
- 判断：先验证纯密码学边界，再接数据库和 HTTP，可把算法问题与持久化问题分离。
- 操作：新增 `tests/unit/auth/test_api_keys.py`，注入确定性随机字节，检查 prefix、正确/错误 key、hash 和 repr。
- 预期：因 `app.auth.api_keys` 不存在而收集失败。
- 实际：pytest 收集失败：`ModuleNotFoundError: No module named 'app.auth'`。
- 问题与处理：RED 与缺失模块一致；实现版本化 scrypt 编码、16-byte salt、固定成本、常量时间 digest 比较、prefix 解析和 `SecretStr` 明文包装。
- 效果与边界：实现后 `1 passed`。测试不接数据库，不能证明 ORM 不保存明文。

## P1-005 — 有效 API Key 到 Principal 的 RED

- 目标：有效候选记录必须返回完全由服务端记录派生的 Principal，并更新 last_used。
- 判断：认证决策与 SQLAlchemy 查询分开，通过公开 lookup 协议测试，可复用 fake clock 且不把测试绑定到 ORM。
- 操作：新增 `tests/unit/auth/test_authentication.py`，使用内存 lookup 和固定 UUID/时钟。
- 预期：因 `app.auth.service`、principal 或 domain enum 不存在而收集失败。
- 实际：pytest 收集失败：`ModuleNotFoundError: No module named 'app.auth.service'`。
- 问题与处理：文件计划新增实际需要的 `app/domain/enums.py`，集中保存 tenant/API Key 状态，不创建后续 Run/Job 枚举。
- 实现：增加 Principal、候选记录、lookup 协议和认证服务；scrypt 验证放入线程，避免阻塞事件循环；未知/错误候选使用 dummy hash 并抛同一异常。
- 效果与边界：实现后 `1 passed`。该测试不证明数据库查询带 prefix/tenant 条件。

## P1-006 — Revoked API Key RED

- 目标：hash 正确但已撤销的 key 必须失败，且不更新 last_used。
- 判断：先锁定撤销语义，再分别增加过期和 tenant 状态；避免一次写完所有状态分支。
- 操作：新增 revoked 候选测试，期待统一 `InvalidAPIKeyError`。
- 预期：当前实现只检查 hash，会错误返回 Principal，因此测试在行为断言处失败。
- 实际：既有有效测试通过；revoked 测试失败为 `DID NOT RAISE InvalidAPIKeyError`。
- 问题与处理：RED 精确证明状态检查缺失；在 hash 验证之后增加 ACTIVE 状态判断，保留错误 key 和 revoked key 都承担 scrypt 成本的顺序。
- 效果与边界：实现后认证文件内 `2 passed`；不测 HTTP 401 映射。

## P1-007 — Expired API Key RED

- 目标：明确到期边界；当 `expires_at == now` 时密钥已经失效，且不得更新 `last_used`。
- 判断：使用“到期时间不晚于当前时间”语义比只检查 `< now` 更安全，也避免在恰好到期的一瞬间多放行一次。
- 操作：增加 active key、active tenant、正确 hash、`expires_at=now` 的测试。
- 预期：当前实现尚未检查到期时间，因此测试应在 `pytest.raises` 处失败。
- 实际：测试失败为 `DID NOT RAISE InvalidAPIKeyError`，其余两个认证测试通过。
- 问题与处理：只新增 `expires_at is not None and expires_at <= now` 分支，没有提前实现 tenant 状态判断。
- 效果与边界：实现后认证文件内 `3 passed`；尚未覆盖数据库时区列与 HTTP 映射。

## P1-008 — Disabled tenant RED

- 目标：即使 API Key 本身有效，所属租户被禁用后也必须拒绝认证，且不得更新 `last_used`。
- 判断：租户状态是所有租户资源访问的总开关，必须在生成 Principal 前执行，不能只依赖各业务路由自行判断。
- 操作：增加正确 hash、active key、disabled tenant 的测试。
- 预期：当前实现尚未检查 tenant 状态，因此测试应在 `pytest.raises` 处失败。
- 实际：测试失败为 `DID NOT RAISE InvalidAPIKeyError`，其余三个认证测试通过。
- 问题与处理：新增 `tenant_status is not TenantStatus.ACTIVE` 判断；保持 hash 验证先执行，从而让 revoked、expired、disabled 与错误 secret 都走同类昂贵校验路径。
- 效果与边界：实现后整个认证单元目录 `5 passed`；这证明纯认证策略，不证明数据库 lookup、统一 401 响应或并发更新行为。

## P1-009 — 内容寻址存储首个 RED 与实现范围偏差

- 目标：证明 artifact 的 SHA-256、相对路径和大小均由服务端内容派生，并正确写入本地根目录。
- 判断：文件系统原语应独立于 ORM 和 HTTP；Dataset service 以后只组合它与短数据库事务。
- 操作：先增加 `put_bytes` 测试，期望路径为 `<sha256 前两位>/<完整 sha256>`。
- 预期：因 `app.artifacts` 尚不存在而收集失败。
- 实际：收集失败为 `ModuleNotFoundError: No module named 'app.artifacts'`。
- 实现：增加异步 facade，把阻塞文件 I/O 放在线程；临时文件与目标同目录，写入后 `flush` + `fsync`，使用硬链接进行原子、create-only 发布，并在 `finally` 清理临时文件。
- 问题与处理：首个实现同时写入了顺序复用与失败清理，超出了首条测试能证明的最小范围。这是 TDD 粒度偏差，保留记录，不把后续直接 GREEN 改写为 RED。
- 效果与边界：首条实现后 `1 passed`；只证明基础内容寻址路径。

## P1-010 — 物理去重回归测试（首次即 GREEN）

- 目标：相同内容重复保存时不改写现有文件，也不遗留第二个物理文件。
- 判断：内容寻址只有配合 create-only 发布和复用语义，才能安全承担跨 dataset 的物理去重。
- 操作：连续保存同一 bytes，检查第二次 `created=False`、mtime 不变且根目录只有一个文件。
- 预期：由于 P1-009 已提前实现复用，该测试应直接通过；它是回归测试，不是 RED。
- 实际：artifact 测试目录 `2 passed`。
- 问题与处理：无代码修改；明确标注首次即 GREEN。
- 效果与边界：证明单进程顺序复用；并发竞争主要由 create-only 硬链接保证，尚未做并发压力测试。

## P1-011 — 已存在 artifact 完整性 RED

- 目标：摘要路径若已有损坏、目录或符号链接，不能被当作正确 artifact 静默复用。
- 判断：只检查“文件存在”会把磁盘损坏永久固化进内容寻址层，必须同时检查类型、大小和摘要。
- 操作：预先在正确摘要路径写入错误内容，再保存原始 bytes，期待 `ArtifactIntegrityError`。
- 预期：当前实现没有该异常和验证，因此先收集失败。
- 实际：收集失败为 `ImportError: cannot import name 'ArtifactIntegrityError'`。
- 问题与处理：增加完整性异常；在顺序复用和并发发布竞争两条路径中均验证非符号链接普通文件、大小和流式 SHA-256。
- 效果与边界：实现后 `3 passed`；检测到损坏时拒绝，不在此层自动修复或覆盖，避免掩盖运维问题。

## P1-012 — 发布失败清理回归测试（首次即 GREEN）

- 目标：原子发布系统调用失败后不遗留 `.tmp` 文件。
- 判断：失败清理是存储边界的必要验收项，即使代码已存在也必须用故障注入固定。
- 操作：替换 `os.link` 令其抛出模拟 `OSError`，断言异常透传且 artifact 根目录无文件。
- 预期：P1-009 已使用 `finally`，所以测试应直接通过。
- 实际：整个 artifact 单元测试目录 `4 passed`。
- 问题与处理：无代码修改；明确标注首次即 GREEN。
- 效果与边界：证明发布阶段失败的临时文件清理；未模拟断电、磁盘硬件故障或跨设备文件系统（临时文件设计为同目录，正常不会跨设备）。

## P1-013 — 合法 JSONL 最小 RED

- 目标：合法 UTF-8 JSONL 保留原始 bytes，并产出服务端摘要、大小和 case 数；额外字段允许，`expected_answer: null` 允许。
- 判断：先建立成功路径，再逐个加入拒绝条件，可确保错误用例不是因为基础解析从未可用。
- 操作：增加两行中英文混合 JSONL，其中包含额外字段和 null answer。
- 预期：`app.datasets` 尚不存在，pytest 应收集失败。
- 实际：`ModuleNotFoundError: No module named 'app.datasets'`。
- 问题与处理：增加最小 `ValidatedJSONL` 和摘要/计数实现，没有提前实现格式拒绝。
- 效果与边界：实现后 `1 passed`；此时函数名虽为 validate，但只具备成功路径，后续 RED 用于补齐拒绝语义。

## P1-014 — 文件、行数和单行字节上限 RED

- 目标：分别证明默认或注入限制下，超文件、超 case 数、超单行 bytes 都被拒绝，并给出可用的错误 code/行号。
- 判断：先执行所有字节级上限，再做解码和 JSON，可在昂贵解析前拒绝资源滥用。
- 操作与实际：
  1. 文件超限测试先因 `DatasetValidationError`/`JSONLValidationLimits` 不存在而收集失败；
  2. 增加限制值对象与 `file_too_large` 后 `2 passed`；
  3. 两行但上限一行的测试失败为 `DID NOT RAISE`；
  4. 增加 `too_many_cases` 和首个超限行号后 `3 passed`；
  5. 单行超限测试失败为 `DID NOT RAISE`；
  6. 改为显式分行并增加 `line_too_large` 后 `4 passed`。
- 问题与处理：末尾一个换行符不计算为空 case；这是常见 JSONL 文件结尾，不能误拒绝。
- 效果与边界：字节限制可注入、默认值为 10 MiB/10,000/1 MiB；尚未证明 HTTP 读取本身只读取 `max+1`。

## P1-015 — 空行和空文件 RED

- 目标：拒绝内部空白行与零 case 文件，同时允许最后一个换行符。
- 判断：空行会破坏“一行一个 case”的定位语义；空文件不应创建不可用 version。
- 操作与实际：
  - 内部空行测试先失败 `DID NOT RAISE`，增加 strip 后的空行判断后 `5 passed`；
  - 空文件测试先失败 `DID NOT RAISE`，增加 `empty_file` 后 `6 passed`。
- 问题与处理：CRLF 的 `\r` 会被 JSON 空白规则接受；只有纯空白行被拒绝。
- 效果与边界：错误携带确定的行号；空文件错误不携带伪造行号。

## P1-016 — UTF-8 与 JSON 语法 RED

- 目标：非法编码与非法 JSON 都应指向具体行，并使用不同稳定 code。
- 判断：逐行严格解码可给出比整文件解码更可操作的位置；JSON 语法检查必须发生在字段 schema 前。
- 操作与实际：
  - 第二行含 `0xff` 时先失败 `DID NOT RAISE`，逐行 strict UTF-8 解码后 `7 passed`；
  - 第二行截断 JSON 时先失败 `DID NOT RAISE`，捕获 `JSONDecodeError` 后 `8 passed`。
- 问题与处理：一次 GREEN 验证命令误把本次进程的 `UV_PYTHON_INSTALL_DIR` 指向 `.uv-cache`；命令使用既有 `.venv` 和 `--no-sync`，没有安装或改写 Python，随后恢复 `.codex-python`。
- 效果与边界：解析错误不会泄露整行上传内容；错误信息只报告类别与行号。

## P1-017 — JSON object 与字段 schema RED

- 目标：每行必须为 object，并满足 `case_id`、`question`、`expected_answer`、`metadata` 合同。
- 判断：Pydantic schema 可集中执行严格类型、必填、非空和 extra allow 规则，避免手写分支与未来 API schema 漂移。
- 操作与实际：
  - `[]` 合法 JSON 先失败 `DID NOT RAISE`；增加 object 判断后 `9 passed`；
  - 参数化 9 个字段负例首次全部失败 `DID NOT RAISE`；
  - 增加 strict、`extra="allow"` 的 `DatasetCase`，并拒绝空白 case/question 后 `18 passed`。
- 问题与处理：`expected_answer` 使用 `Any` 且无默认值，因此“必须存在但 JSON 值可为 null/对象/数组”；这是合同原文，而不是假设答案一定是字符串。
- 效果与边界：字段错误统一为 `invalid_record` 与行号；当前不向客户端暴露 Pydantic 内部结构。

## P1-018 — 重复 case ID RED

- 目标：同一文件内第二次出现相同 `case_id` 时拒绝并报告第二次出现的行。
- 判断：version 的 case 标识必须稳定唯一，否则后续评测结果无法无歧义关联。
- 操作：两行使用相同 case ID、不同 question。
- 预期与实际：当前实现未维护集合，测试失败 `DID NOT RAISE DatasetValidationError`。
- 问题与处理：在 schema 验证成功后加入集合检查，避免把缺失或错误类型的 case ID 误报为重复。
- 效果与边界：实现后 JSONL 单元测试 `19 passed`；当前唯一性按原始字符串精确比较，不擅自 trim 或改变大小写。

## P1-019 — ORM 元数据 RED

- 目标：在连接数据库前固定五张 Phase 1 表、API Key 不含明文列、tenant 外键及 dataset version 唯一约束。
- 判断：元数据测试能快速发现字段和约束漂移，但不能替代 PostgreSQL 实际执行 migration。
- 操作：新增 `tests/unit/persistence/test_orm_models.py`；这是原文件计划之外的必要测试文件，已补入计划。
- 预期与实际：因 `app.persistence.orm_models` 不存在而收集失败。
- 实现：增加命名约定、UUID 主键、时区时间、状态枚举、外键、检查约束、唯一约束和查询索引；只创建 tenants、api_keys、datasets、artifacts、dataset_versions。
- 问题与处理：初版 artifact 采用全局 SHA 记录，未完整携带原始附件要求的 tenant/artifact 类型/media type 字段；见 P1-020 的重新核对与修正。
- 效果与边界：初版实现后 `4 passed`，局部 Ruff/mypy 通过；这些通过只能证明初版测试合同，不能证明合同本身已正确覆盖原始要求。

## P1-020 — 重新核对原始附件并纠正 Artifact 数据归属

- 目标：在 migration 前确认 ORM 没有偏离用户最初数据库字段要求。
- 判断：阶段设计文档没有完整列出 artifact 表字段，原始附件才是上位需求，因此必须回读而不是沿用方便实现的假设。
- 操作：检索原始附件中 Phase 1、artifacts 和安全边界；发现明确要求 `tenant_id`、`artifact_type`、`media_type`、`byte_size`。
- 纠正方案：
  - 物理内容仍按 SHA 全局去重；
  - artifact 数据库记录按 tenant 拥有；
  - 唯一键为 `(tenant_id, artifact_type, sha256)`；
  - 不对 `storage_path` 做全局唯一，以允许不同 tenant 记录引用同一物理内容；
  - Phase 1 类型只有 `dataset_source`；
  - 原始总表中的 `run_id` 等 Run 关联留到 Phase 2，因为当前不存在可引用的 Run 表。
- RED：先修改 ORM 测试；现模型失败，缺少 `tenant_id`、`artifact_type`、`media_type`、`byte_size` 四列。
- 实现：增加 `ArtifactType`、tenant 外键和上述字段，将 `size_bytes` 更名为原需求的 `byte_size`，调整唯一约束和索引。
- 效果与边界：修正后 ORM 测试 `4 passed`，Ruff/mypy 通过；物理文件本身不编码 tenant，授权仍由数据库访问链保证。

## 实施后的文件计划调整

最初文件计划是设计前的预估，实施中按实际职责做了以下调整。保留这些偏差是为了说明“为什么需要改计划”，而不是让最终文件树反过来伪装成一开始就完全预见：

- 未创建 `app/api/dependencies.py`：tenant principal 是认证职责，依赖实现放在 `app/auth/dependencies.py`，避免出现两个含义重叠的依赖模块。
- 新增 `app/auth/repository.py`：认证策略与 SQLAlchemy 查询、条件更新需要独立测试，不能全部塞入 service。
- 新增 `app/core/event_loop.py` 与 `tests/conftest.py`：真实运行 Alembic 时发现 Windows 默认 Proactor 与 psycopg async 不兼容，需要一个应用、脚本、Alembic、Uvicorn 和 pytest 共用的 Selector loop factory。
- 新增 `scripts/__init__.py`：让运维脚本可以稳定通过 `python -m scripts.<name>` 调用和导入测试。
- 新增 `tests/unit/auth/test_authentication.py`、`tests/unit/auth/test_repository.py`、`tests/unit/datasets/test_service.py`、`tests/unit/scripts/test_api_key_scripts.py` 和 `tests/unit/test_event_loop.py`：分别覆盖纯认证策略、tenant-aware SQL、事务编排、密钥运维边界和 Windows loop 合同。
- 修改 `.github/workflows/ci.yml`、`Dockerfile`、`deploy/compose.yaml` 和 `app/cli.py`：Phase 1 不只是库代码，migration、API 启动和运维入口也必须使用同一套 schema 与事件循环约束。
- 修改 `tests/unit/test_config.py`：上传限制变成配置后，需要证明环境变量能加载且上限受控。

## P1-021 — Phase 1 migration 与约束名称核对

- 目标：把 ORM 合同转换成可审查、可回滚的 PostgreSQL DDL，且 revision 链只有一个 head。
- 判断：本阶段必须交付手写且可审查的 migration；只依赖 ORM `create_all()` 会绕过 Alembic 历史，也不能证明部署顺序。
- 操作：
  - 新增 `20260729_0002_identity_datasets.py`；
  - 创建 `tenants`、`api_keys`、`datasets`、`artifacts`、`dataset_versions`；
  - 增加外键删除语义、状态/正数检查、tenant 唯一约束和查询索引；
  - 更新 `alembic/env.py` 的 `target_metadata` 为 ORM `Base.metadata`；
  - 执行 `alembic heads`、`alembic history` 与 `alembic upgrade head --sql`。
- 首次问题：显式 constraint 名已经带表名前缀，而 `MetaData` naming convention 又自动加一次前缀，离线 SQL 出现重复命名片段。DDL 可以生成，但名称可读性差，并会让 ORM 与 migration 的名称难以比较。
- 处理：显式名称只保留短语义名，让 naming convention 统一生成最终名称；重新生成离线 SQL逐项核对。
- 最终效果：
  - 唯一 head 为 `20260729_0002`；
  - 历史为 baseline → identity/datasets；
  - PostgreSQL offline SQL 完整生成并包含五张表、约束和索引。
- 边界：离线 SQL 证明脚本可加载和 DDL 可生成，不证明它已经在真实 PostgreSQL 上执行。

## P1-022 — SQLAlchemy 认证仓储、统一 401 与并发状态复核

- 目标：把纯认证策略接到真实 ORM 查询，同时避免“验证通过后、写入 `last_used_at` 前密钥被撤销”仍放行的竞态。
- 判断：一次 SELECT 后无条件 UPDATE 只适合演示，不足以支撑撤销语义；最终写操作必须再次携带 active、未过期和 tenant active 条件。
- 操作：
  - prefix lookup 只按安全前缀查找，并 join tenant 取得状态；
  - malformed/unknown prefix 走固定 dummy scrypt 校验；
  - 使用 `hmac.compare_digest` 比较派生结果；
  - 成功路径调用条件 UPDATE：重新检查 key active、`expires_at > now` 或为空，并以 `EXISTS` 复核 tenant active；
  - UPDATE 未命中时认证失败，不生成 Principal；
  - 每次认证使用短生命周期 session，避免把数据库 session 泄漏到整个 HTTP 请求。
- HTTP 合同：缺失、malformed、unknown、错误 secret、revoked、expired、disabled tenant 和并发撤销都映射到同一 `401`：

  ```json
  {
    "error": {
      "code": "invalid_api_key",
      "message": "Authentication credentials are invalid."
    }
  }
  ```

- 问题与处理：只测试内存 lookup 无法证明 SQL 带 tenant/status 条件，因此增加 PostgreSQL dialect 编译测试，直接检查 SELECT/UPDATE 结构。
- 效果：API Key ORM 没有 plaintext/secret/api_key 列；明文只存在于生成结果的 `SecretStr`，存储值是带版本、参数和随机 salt 的 scrypt 编码。
- 边界：统一昂贵校验减少明显的 unknown-prefix timing 差异，但没有速率限制和容量测试，不能声称抵御认证 DoS。

## P1-023 — Dataset HTTP 合同与有界 multipart 入口

- 目标：提供 tenant-scoped dataset create/get，以及 immutable version create/get 四个端点。
- 判断：tenant 必须完全来自认证 Principal；即使客户端“恰好传了正确 tenant_id”，也应拒绝，避免以后出现字段混淆或越权回归。
- 新增端点：
  - `POST /api/v1/datasets`
  - `GET /api/v1/datasets/{dataset_id}`
  - `POST /api/v1/datasets/{dataset_id}/versions`
  - `GET /api/v1/datasets/{dataset_id}/versions/{version_id}`
- 输入边界：
  - dataset JSON body 使用 `extra="forbid"`，请求体 `tenant_id` 返回 `422 invalid_request`；
  - version 只接受 `application/jsonl` 与 `application/x-ndjson`，其他媒体类型返回 `415 unsupported_media_type`；
  - `UploadFile` 只读取 `max_file_bytes + 1`，先在 HTTP 层返回 `413 file_too_large`，不让任意大请求进入 JSON 解析；
  - 客户端文件名不进入 storage path 或数据库授权判断。
- 错误边界：请求校验、JSONL 校验、名称冲突、重复 version、认证失败和资源不存在都转换成稳定 envelope；跨 tenant 与不存在共享 `404 resource_not_found`。
- 依赖问题：FastAPI multipart 路由要求显式安装 `python-multipart`。加入 `pyproject.toml` 后更新 `uv.lock`，实际锁定版本为 `0.0.32`。
- 效果：14 个 API 测试覆盖成功响应、统一错误、tenant 来源、媒体类型、文件上限、跨 tenant 和 service 调用参数。
- 边界：API fake service 测试证明 HTTP 合同，不证明 PostgreSQL 事务或文件落盘。

## P1-024 — Dataset service 的短事务与跨 tenant 副作用修正

- 目标：验证 JSONL、保存物理内容、创建 tenant-owned artifact 元数据，并为 dataset 分配严格递增的 immutable version。
- 判断：
  - JSONL 解析与磁盘 `fsync` 都可能较慢，不应持有数据库行锁；
  - version number 分配必须在锁住 dataset 行的短事务中进行；
  - 授权失败必须尽量在文件系统副作用之前返回。
- 初始编排：validate → artifact store → transaction 中 tenant-scoped dataset lock → artifact/version insert。
- 新 RED：跨 tenant 上传应返回 not found，且 artifact store 调用次数必须保持 0。初始编排虽然最终返回 404，却已提前写入物理文件，测试暴露了“结果安全但有无授权副作用”的缺陷。
- 修正编排：
  1. 在事务外执行纯 JSONL 校验；
  2. 先做 tenant-scoped dataset 存在性读取；
  3. 只有资源属于 Principal tenant 才落盘；
  4. 开启短事务并以 tenant + dataset id 重新查询、`FOR UPDATE` 锁行；
  5. 再次检查同 dataset SHA；
  6. 使用 PostgreSQL `ON CONFLICT` 取得或创建当前 tenant 的 artifact 元数据；
  7. 读取 `max(version)`，创建下一版本并提交。
- 为什么要两次查询：第一次减少未授权文件副作用；第二次在写事务内重新建立授权和并发事实，不能相信事务外的旧结果。
- 并发保护：dataset 行锁串行化同一 dataset 的 version 分配；数据库唯一约束 `(dataset_id, version)` 和 `(dataset_id, sha256)` 仍作为最后防线。
- 效果：5 个 service 单元测试覆盖 tenant 查询、锁查询、重复 SHA、版本分配与“跨 tenant 不调用 storage”。
- 边界：若文件落盘后数据库事务失败，可能留下无引用物理文件；Phase 1 明确不实现 artifact GC，但不会创建错误的 tenant/version 元数据。

## P1-025 — Artifact 发布前复核与符号链接边界

- 目标：补强“内容寻址”不等于“只在内存算一次 SHA”的缺口。
- 判断：写临时文件之后、原子发布之前必须重新从磁盘读取并确认 byte size/SHA；否则测试注入、磁盘故障或未来代码回归可能把错误 bytes 发布到正确摘要路径。
- RED：故障注入令临时文件内容在首次摘要计算后发生变化；旧实现仍发布，测试失败。
- 处理：
  - `flush` + `fsync` 后从临时文件流式重算 size/SHA；
  - 不一致时抛 `ArtifactIntegrityError`，且 `finally` 删除临时文件；
  - 已有目标也重新校验普通文件、size 和 SHA；
  - 拒绝目标文件符号链接；
  - 进一步增加两位摘要目录为符号链接的测试和拒绝逻辑，阻止写入被引导到 artifact root 外。
- 发布方式：临时文件与目标同目录；`os.link(temp, target)` 提供 create-only 原子发布。若并发者先发布，当前进程验证胜者内容后复用。
- 效果：6 个 artifact 测试覆盖服务端路径、顺序复用、损坏已有文件、发布失败清理、临时内容变化和符号链接目录。
- 边界：这是本地单文件系统策略；NFS、对象存储、多主机共享和硬件断电一致性需要各自的后端协议与集成测试。

## P1-026 — 真实 PostgreSQL 集成合同

- 目标：不用 SQLite，定义一条在真实 PostgreSQL 上证明身份、tenant 隔离、事务约束和物理去重的测试路径。
- 操作：
  - 创建两个 tenant 和两把真实格式/哈希 API Key；
  - 通过 ASGI HTTP 走完整 Bearer 认证；
  - 创建 dataset 与 version；
  - 同 dataset 重复 SHA 返回 409；
  - tenant B 对 tenant A 的 dataset/version GET 和 upload 均返回 404；
  - 跨 tenant upload 不新增物理文件；
  - tenant B 上传相同 bytes 时，数据库有两条 tenant-owned metadata，磁盘只有一个内容文件；
  - revoke 后原 key 返回 401；
  - 检查数据库 key hash 中不存在原始明文。
- 数据清理：测试只删除自己创建的 UUID 行，避免清空共享开发库。
- 门控：只有 `EVALOPS_RUN_INTEGRATION=1` 才运行；CI 先执行 migration，再运行 integration marker。
- 本机实际：没有 PostgreSQL/Redis 服务，最终全量测试中两条 integration 测试明确 skip；skip 不计为动态通过。
- 边界：合同存在且被 CI 配置引用，但本轮没有 push，也没有本地服务，所以仍未获得真实数据库成功证据。

## P1-027 — 开发 API Key 创建/撤销脚本

- 目标：提供最小可操作入口，同时守住“明文只显示一次”和“不要把完整 secret 放入命令历史”的边界。
- 创建脚本：
  - 按 slug 创建 tenant，或复用现有 active tenant；
  - 生成密钥并只提交 hash/prefix；
  - 只有事务提交成功后才把明文打印一次；
  - disabled tenant 或同名 active key 冲突时明确失败。
- 撤销脚本：
  - 只接受精确 `evk_<12 hex>` 安全前缀；
  - 若输入完整 key，解析器主动拒绝；
  - 条件 UPDATE 只撤销 active key，并记录 `revoked_at`。
- 首次类型问题：mypy 指出脚本读取了不存在的 `generated.key_prefix`；生成结果真实字段名是 `prefix`。
- 处理：改为 `generated.prefix`，随后脚本单元测试和 `mypy scripts` 通过。
- 效果：运维脚本可以用 `python -m scripts.create_dev_api_key` / `revoke_api_key` 运行；Dockerfile 也复制 `scripts/`。
- 边界：这不是完整的管理员 RBAC、审计或密钥轮换系统，只是本地/早期环境的受控入口。

## P1-028 — 配置、应用 wiring、Compose 与 CI 更新

- 目标：确保实现不只在 isolated unit 中存在，而是被真实 app factory、命令行、容器和 CI 路径引用。
- 操作：
  - Settings 增加文件总字节、case 数和单行字节限制，并设硬上限防止错误环境变量把保护完全关闭；
  - FastAPI lifespan 创建 async session factory、认证 lookup、artifact store 和 dataset service；
  - 注册 dataset router 与统一异常处理器；
  - Docker/Compose 传入上传限制，API 使用与 psycopg 兼容的 loop factory；
  - CI 的阶段描述与 integration 路径更新到 Phase 1；
  - CLI 与运维脚本统一使用事件循环 helper。
- 判断：配置上限可以被合理调整，但不能让一个环境变量把内存保护提升到任意大值；因此同时存在默认值与受控最大值。
- 效果：`uv lock --check` 通过，配置测试覆盖默认值、环境覆盖和 secret URL 不泄漏。
- 边界：Compose 文件存在不等于容器已经构建或启动；见 P1-035。

## P1-029 — Windows psycopg/asyncio 兼容问题诊断

- 触发：首次执行在线 `alembic current`，在连接数据库之前收到 psycopg 明确错误：Windows 的 `ProactorEventLoop` 与 psycopg async 不兼容。
- 为什么这不是“本机没数据库”：错误发生在连接尝试前；即使启动 PostgreSQL，默认 loop 仍会失败，所以不能只记成环境缺依赖。
- 官方依据：
  - Python 3.12 在 Windows 默认使用 Proactor，而 `SelectorEventLoop` 可显式创建；
  - psycopg 官方 async 文档明确要求 Windows 使用 Selector，而不是默认 Proactor；
  - 参考：<https://docs.python.org/3.12/library/asyncio-eventloop.html#asyncio.SelectorEventLoop>
  - 参考：<https://www.psycopg.org/psycopg3/docs/advanced/async.html>
- 方案判断：只在 Alembic 内临时改 policy 会让 API、脚本和测试仍有相同隐患；因此建立一个共享 loop factory。
- 实现：
  - `create_psycopg_compatible_event_loop()` 返回 Selector loop；
  - `run_with_psycopg_compatible_event_loop()` 供 Alembic、CLI 和脚本执行 coroutine；
  - Uvicorn 本地命令、Dockerfile 和 Compose 显式传 `--loop app.core.event_loop:create_psycopg_compatible_event_loop`；
  - pytest 使用 `pytest_asyncio_loop_factories` 让所有 async 测试运行在同类 loop 上。
- 测试过程：
  - 在 pytest hook 前，异步测试实际拿到 Proactor，RED；
  - 加 hook 后，代码复核发现参数名必须与插件 spec 的 `config`/`item` 一致，因此在运行前把临时 `_config`/`_item` 改为规范名称；
  - factory、runner、pytest running loop 三个测试最终全部通过。
- 最终在线证据：修复后的 `alembic current` 不再报 loop 错误，而是在 2 秒连接参数下到达 `psycopg.errors.ConnectionTimeout`。这证明 loop 入口已修复，也确认本机 5432 没有可用 PostgreSQL。
- 取舍：当前统一使用标准 Selector，优先保证跨入口一致与 Windows 正确性；尚未做 uvloop 性能对比。

## P1-030 — Uvicorn 可执行 smoke

- 目标：确认 app factory、lifespan、router、middleware 与自定义 loop factory 能在真实服务器进程组合启动。
- 操作：在 `127.0.0.1:8765` 启动 Uvicorn，然后请求 `/health/live` 与 `/openapi.json`。
- 首次检查问题：脚本把 request ID 当成健康检查 JSON 字段，因此得到 `False`；实际合同一直是 `x-request-id` 响应头。
- 第二个工具问题：本机 `Invoke-WebRequest` 读取响应时触发 PowerShell 自身 `NullReferenceException`，而同一服务此前已被 `Invoke-RestMethod` 成功访问。
- 处理：用 `curl.exe --include` 读取原始 HTTP 响应，不修改服务代码。
- 实际结果：
  - liveness 返回 HTTP 200 与 `{"status":"alive"}`；
  - `x-request-id: abb49468-7a1f-496c-bdfa-60847277734e` 可解析为 UUID；
  - OpenAPI 存在四条 Phase 1 dataset/version 路由。
- 退出问题：PTY 连续发送 Ctrl+C 没有让前台 Uvicorn 退出；为避免遗留服务，只终止本次启动日志明确给出的 PID `38016`，随后 session 关闭。没有按名称批量杀进程。
- 边界：该 smoke 不访问数据库，所以不证明认证成功路径或 migration 已应用。

## P1-031 — 验收命令环境遗漏与旧 pytest 缓存

- 目标：让测试结果反映代码，而不是沙箱缓存权限。
- 首次问题：并行跑事件循环测试、Ruff 和 mypy 时漏设项目内 `UV_CACHE_DIR`；uv 尝试创建用户级 `C:\Users\xuan\AppData\Local\uv\cache`，被沙箱拒绝。
- 处理：恢复统一的 `.codex-python` 与 `.uv-cache` 环境变量，并使用 `--no-sync`，避免网络或用户目录写入。
- 结果：事件循环 `3 passed`，局部 Ruff 与 mypy 通过。
- 另一个环境问题：pytest 想更新旧 `.pytest_cache` 时收到访问拒绝；只读检查也无法列出其内容或 ACL，说明它不属于当前可安全管理的目录状态。
- 处理判断：缓存不参与测试正确性，不为了“消除警告”提权或破坏性删除；最终命令使用 `-p no:cacheprovider`。
- 效果：后续结果没有缓存权限警告；旧 `.pytest_cache` 保持未触碰且已被 `.gitignore` 忽略。

## P1-032 — 全量 pytest 并发方式错误与可信重跑

- 目标：同时取得非集成和全量测试结果。
- 首次操作：为了节省时间并行启动两次 pytest。
- 实际问题：`pyproject.toml` 固定 `--basetemp=.pytest-tmp`，两个 Windows 进程同时删除/创建同一目录，互相造成 `PermissionError`；其中一份摘要为 `63 passed, 10 errors`，错误全部发生在 `tmp_path` setup，而不是产品断言。
- 判断：这次结果不可作为通过，也不能据此改业务代码；根因是测试调度共享目录。
- 修正：
  - 串行运行；
  - 非集成使用独立 `--basetemp=.pytest-tmp-nonintegration`；
  - 全量使用独立 `--basetemp=.pytest-tmp-full`；
  - 完成后解析并校验两个绝对路径确实位于仓库内，再删除本轮生成目录。
- 最终结果：
  - 非集成：`71 passed, 2 deselected in 3.71s`；
  - 全量：`71 passed, 2 skipped in 3.70s`；
  - skip 原因分别明确要求 migrated real PostgreSQL，以及 real PostgreSQL + Redis。
- 学习结论：可以并行 lint/mypy/lock 等只读检查，但多个 pytest 进程不能共享同一个 `basetemp`。

## P1-033 — 最终静态质量与 YAML 解析

- 执行与结果：
  - `uv lock --check`：48 packages 成功解析，锁文件一致；
  - `ruff format --check .`：64 files already formatted；
  - `ruff check .`：All checks passed；
  - `mypy app`：32 source files 无问题；
  - `mypy scripts`：3 source files 无问题。
- YAML 首次问题：用于同时解析 Compose/CI 的 Python one-liner 在 PowerShell/Python 双层引号处转义错误，Python 在读文件前报 `SyntaxError: unterminated string literal`。
- 处理：去掉嵌套 f-string，改成简单字符串拼接的等价只读命令。
- 最终结果：PyYAML 将 `deploy/compose.yaml` 与 `.github/workflows/ci.yml` 都解析为顶层 dict。
- 边界：通用 YAML parser 只能证明语法，不证明 Docker Compose 或 GitHub Actions 的平台级语义。

## P1-034 — Alembic 最终验收

- `alembic heads`：`20260729_0002 (head)`。
- `alembic history`：`20260728_0001 -> 20260729_0002`，且 baseline 前无其他分叉。
- `alembic upgrade head --sql`：成功生成 PostgreSQL transactional DDL；人工核对五张表、外键、唯一约束、check 和索引。
- `alembic current`：使用 Selector loop 后到达数据库连接，最终 `ConnectionTimeout`。
- 达成效果：migration 文件、revision 链和 offline PostgreSQL 方言输出通过；Windows loop 缺陷已从“入口即失败”修到“正常尝试连接”。
- 未达成：本机没有真实 PostgreSQL，未执行 online upgrade/current 成功路径，integration 也未动态通过。

## P1-035 — Docker/Compose 最终检查

- 操作：实际运行 `docker --version` 与 `docker compose version`；此前也尝试过构建入口。
- 实际：PowerShell 均返回 `CommandNotFoundException`，系统找不到 `docker`。
- 判断：安装 Docker Desktop 涉及系统级软件、GUI/虚拟化和用户授权，超出仓库内 Phase 1 实现步骤；不擅自安装。
- 效果：Dockerfile 与 Compose YAML 已更新、YAML 可解析，但 build/up 均不能标为通过。
- 后续验证位置：安装 Docker 的开发机，或 push 后的 GitHub Actions；本阶段没有 push，因此 CI 也未运行。

## P1-036 — Phase 1 验收结论

| 验收项 | 最终状态 | 证据或边界 |
|---|---|---|
| API Key 只存 hash、只显示一次 | 通过（静态/单元） | ORM 列检查、生成/脚本测试 |
| revoked/expired/disabled/unknown | 通过（单元/API） | 统一 401、dummy hash、条件 UPDATE |
| tenant 只能来自 Principal | 通过（API/查询合同） | body `tenant_id` 422；SQL tenant 条件 |
| dataset create/get 与 immutable version | 通过（单元/API） | 14 API + 5 service 测试 |
| JSONL 安全边界 | 通过（单元/API） | 19 validation 测试与 HTTP size/media 测试 |
| artifact 内容寻址与物理去重 | 通过（单元） | 6 storage 测试 |
| Alembic revision/offline DDL | 通过 | 唯一 head、history、offline SQL |
| 真实 PostgreSQL/Redis | 未验证 | 本机连接超时；2 integration tests skipped |
| Uvicorn smoke | 通过 | HTTP 200、UUID request header、4 routes |
| Docker build/Compose up | 未运行 | 本机无 docker |
| CI | 未运行 | 本阶段不 push |

结论：Phase 1 的仓库内实现与本机可执行验收已完成；依赖真实 PostgreSQL/Redis/Docker/远端 CI 的项目保持诚实未验证。没有开始 Phase 2 的 Run/Job、Worker/Reaper、队列、幂等或崩溃恢复。

## P1-037 — Git 分组提交

- 本机全局 Git identity 未配置。为避免修改用户全局设置，每次提交只通过命令级 `-c user.name=Codex -c user.email=codex@localhost` 提供 identity。
- 提交前每一组都执行 `git diff --cached --check`。
- 已创建：
  - `aca08ae docs: define phase 1 domain and security contracts`
  - `8d20657 feat(auth): add tenant api key identity and schema`
  - `96d8e46 feat(datasets): add immutable jsonl dataset versions`
  - `16211c7 chore: add phase 1 runtime and operator tooling`
- README、工程日志与本逐步日志位于最后的文档提交；该提交无法在自身内容中可靠记录自己的 hash，最终 hash 以 `git log` 为准。
- 未创建新分支，未 push。
