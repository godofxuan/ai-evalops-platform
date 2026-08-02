# P2-5 Gate 1 质量检查自动化：证据化实施日志

## 0. 阶段元数据

- 日期：2026-08-02；
- 分支：`codex/gate1-evidence-hardening`；
- 起始提交：`b86bc898c27e1065ec649f091e2ae518e1f29511`；
- RED 提交：`a9a1324`，`test(gate1): require automatic gate evaluation`；
- GREEN 提交：`3ee4480`，`feat(gate1): evaluate quality readiness automatically`；
- 数据库 migration：无；
- 正式 500-case / 32-arm Gate：`NOT_RUN`；
- 当前证据状态：`LOCAL_AND_REMOTE_VERIFIED / FORMAL_GATE_NOT_RUN`。

本日志记录的是实验工具合同改进，不是实验结果。文中的 `VERIFIED` 只表示列出的自动化测试和
静态检查已通过，不能被转述为 Worker 扩展性、500-case 性能或生产容量已经验证。

## 1. 为什么现在做、指令是否合适

P2-4 已先固定 Compose 的运行用户、只读根文件系统、capability 和资源上限，因此 P2-5 可以在
较稳定的运行边界上完善 Gate 1 结果判定。该顺序合适，原因是：

1. Gate 自动化依赖 prepared manifest、arm plan、per-arm summary 和原子 final bundle；这些组件
   已在 P1-1 至 P1-5 中建立哈希、schema 和发布边界；
2. `valid_for_capacity_comparison` 已汇总数据库对账、必需 Prometheus 指标和 collector 完整性，
   可以作为不可弱化的客观质量输入；
3. P2-5 不需要修改领域表或线上 API，不引入 migration，回滚面较小；
4. 正式性能阈值仍属于用户，当前任务可以自动判断“证据是否合格”，但不能代替用户决定
   “采用哪个 Worker 数”。

直接把 throughput 最大的 arm 自动设为部署值不合适。吞吐上升可能伴随 p95/p99、数据库等待、
OOM/throttling 或资源余量恶化；而且本仓库还没有用户批准的数值阈值。P2-5 因此只自动化客观
质量门与人工评审就绪状态，不自动化 adoption decision。

## 2. 修改前的代码位置和行为

| 位置 | 修改前行为 | 缺口 |
|---|---|---|
| `scripts/run_load_test.py` | `--confirm-quality-gate` 与 `--confirm-adoption-gate` 是 `store_true` | 只能记录人按过开关，没有任何机器可验证的 gate 内容 |
| `scripts/gate1_preflight.py` | 将两个布尔值直接写入 preflight observations | 布尔授权容易被误读成质量/采纳结果 |
| prepared manifest schema v4 | 只保存 `automatic_worker_count_change=false` 与 `decision_owner=human` | 没有冻结自动质量策略、策略版本或输出 result schema |
| `aggregate_arm_summaries` | 汇总重复点、median/min/max 与负扩展 | 没有质量状态、缺失 arm、无效 arm或人工评审就绪标志 |
| `finalize_gate1_run_evidence` | 只按已观察 summary 生成 aggregate | 没有显式把冻结 `arm_order.json` 的期望 arm 集合传给评估器 |
| aggregate JSON | `automatic_adoption_decision=null` | 虽然没有越权采纳，但也没有说明为何不可采纳或何时可交给人工 |

现有测试主要验证 prepared hash、finalization 原子性、plot 完整性和 per-arm 对账。它们没有断言
aggregate 必须根据“期望 arm”而不是“当前恰好存在的 arm”给出质量结论，所以旧行为可以全部
通过。

## 3. 风险分析

### 3.1 内容为空的确认开关

命令行布尔值不能证明用户定义了什么性能门槛，也不能证明实验结果满足门槛。继续把它命名为
`confirmed` 是兼容性选择，但文档和输出必须明确：它只代表“用户授权开始正式运行”，不是结果
证据。

### 3.2 只汇总已存在记录会产生假完整

如果期望 32 个 arm，但聚合器只收到 31 个，旧实现会自然地汇总 31 个，并且没有字段表明缺少
一个 arm。机器消费者可能把“JSON 能解析”误认为“实验完整”。

### 3.3 自动选择 Worker 会越权

负扩展本身是需要保留的结果，不一定表示实验质量失败。相反，所有 correctness 都通过也不代表
某个 Worker 数应被采用。把 quality 与 adoption 合并会同时污染正确性和容量判断。

### 3.4 schema 不升级会造成静默误读

aggregate 新增 gate 机器语义后，旧 reader 若仍按 result schema v2 理解文件，会看不到新增的
状态。prepared manifest 也需要声明将生成的 result schema 和不可弱化策略。因此本阶段必须
显式升级 schema，而不是把字段悄悄塞进旧版本。

## 4. 冻结的最小合同

### 4.1 自动质量策略

策略 ID 固定为：

```text
all_expected_arms_valid_for_capacity_comparison
```

策略版本为 `1`，并在 prepared manifest 中记录：

```json
{
  "result_schema_version": 3,
  "quality_gate": {
    "automatic_evaluation": true,
    "policy": "all_expected_arms_valid_for_capacity_comparison",
    "policy_version": 1,
    "non_waivable": true
  }
}
```

prepared verifier 对以上值做精确匹配。把 policy 改成允许跳过 invalid arm、删除字段或改变版本，
都会得到 `MANIFEST_INVALID`，不会进入环境 preflight 或任何正式 arm。

### 4.2 expected arm 与 observed arm

正式 CLI 从启动前已读取并通过 prepared 验证的 `arm_order.json` 取得 `arm_plan["arms"]`，将其
显式传给 finalizer。finalizer 不提供“省略 expected arms”的回退，因此直接调用也不能只根据
现有 summary 自我宣布完整。

每个 arm 合同至少绑定：

- `arm_id`；
- workload；
- Worker 数；
- repetition。

以下情况 fail-closed 并抛出 `ExperimentError`：

- expected arm ID 重复；
- expected workload/Worker/repetition 坐标重复；
- observed arm ID 重复；
- observed arm 不在 expected plan；
- 同 arm ID 的 workload/Worker/repetition 与 expected plan 不同；
- arm ID、Worker 数或 repetition 类型/范围非法；
- `valid_for_capacity_comparison` 不是严格 Boolean。

### 4.3 quality gate 状态

状态优先级为：

1. 任一已观察 arm 的 `valid_for_capacity_comparison=false`：`FAILED`；
2. 没有已知无效 arm，但缺少 expected arm：`UNKNOWN`；
3. expected arm 全部存在且全部有效：`VERIFIED`。

输出保留 expected/observed 数量、`missing_arm_ids` 和 `invalid_arm_ids`。这样机器消费者不需要从
group 数量猜测完整性。

`valid_for_capacity_comparison` 已由既有路径 fail-closed：数据库对账违反不变量、必需
Prometheus 指标缺失/失败或 collector missed sample 都会使其为 false。本阶段没有新增可以绕过
这些来源的默认值。

### 4.4 adoption gate 边界

adoption 始终保持：

```json
{
  "status": "NOT_RUN",
  "decision_owner": "human",
  "performance_thresholds_owner": "human",
  "automatic_worker_count_change": false,
  "automatic_adoption_decision": null,
  "selected_worker_count": null
}
```

只有 quality 为 `VERIFIED` 时，`review_readiness` 才是 `READY_FOR_HUMAN_REVIEW`；否则为
`BLOCKED`，并给出 `quality_gate_failed` 或 `quality_gate_unknown`。

`READY_FOR_HUMAN_REVIEW` 不是“建议采纳”，更不是“自动通过 adoption”。它只说明客观正确性和
证据完整性足以让人开始看 throughput、p95/p99、数据库等待、资源余量与负扩展。

负扩展继续写入 `negative_scaling`，不会自动把 quality 设为 FAILED，也不会产生推荐 Worker 数。

### 4.5 schema 版本

| schema 轴 | 修改前 | 修改后 | 原因 |
|---|---:|---:|---|
| prepared manifest | 4 | 5 | 新增 result schema 与不可弱化 gate policy |
| Gate 1 result | 2 | 3 | aggregate 新增机器可读 gate evaluation |
| final bundle layout | 1 | 1 | 文件布局、哈希和原子发布合同没有变化 |
| Prometheus evidence | 2 | 2 | `OBSERVED_ZERO/MISSING/COLLECTION_FAILED` 语义没有变化 |

这些是四个独立版本轴。不能因为 result schema 升为 3，就把 Prometheus evidence schema 或 final
bundle layout 一起无意义升号。

prepared schema v1–v4 和 result schema v1–v2 保持历史只读；不覆盖、不原地迁移、不手工补字段。

## 5. 方案比较

### 方案 A：根据最高吞吐自动选 Worker

优点是实现直观；缺点是需要用户尚未定义的延迟、资源和数据库阈值，会把一次受控单机实验错误
提升为部署决策。拒绝。

### 方案 B：只把两个 `--confirm-*` 改名

能减少术语误解，但仍无法发现缺 arm、无效 arm 或策略篡改。单纯重命名也会破坏已有调用脚本，
收益不足。拒绝作为本次修复。

### 方案 C：冻结不可弱化质量策略，自动计算评审就绪，采纳保持人工

能自动化客观部分，同时尊重用户拥有性能门槛和部署选择权；不需要 migration，也不运行正式
实验。选择。

### 方案 D：本阶段强制用户提供数值 gate-policy 文件

长期可用于把用户批准的 p95、吞吐、资源余量阈值做内容寻址绑定，但当前用户尚未定义这些数值。
Codex 自行编造阈值会越权。因此本阶段只记录 `performance_thresholds_owner=human`，未来在用户
给出策略后另行设计，不用默认值掩盖缺失输入。

## 6. RED → GREEN 证据

### 6.1 RED

先修改测试，未改实现。新增覆盖：

1. 完整且有效的 expected arms 必须得到 quality `VERIFIED`；
2. 缺 expected arm 必须得到 `UNKNOWN` 并阻断人工评审；
3. invalid arm 必须得到 `FAILED`；
4. 重复和 unexpected arm 必须 fail-closed；
5. 负扩展不能触发自动采纳或自动选 Worker；
6. prepared quality policy 被篡改必须 `MANIFEST_INVALID`；
7. final aggregate 与 final manifest 必须声明 result schema v3。

RED 命令在 test collection 阶段失败：

```text
ImportError: cannot import name 'evaluate_gate1_gate_flags'
1 error in 1.44s
```

这证明失败来自旧实现没有评估入口，不是 Docker、PostgreSQL、Redis 或网络环境。

### 6.2 最小 GREEN

新增纯函数 `evaluate_gate1_gate_flags`，让 `aggregate_arm_summaries` 写入
`gate_evaluation`；prepared manifest/verifier 和 finalizer 只增加完成该合同所需的字段与参数。

首轮同一目标集合：

```text
18 passed in 65.19s
```

### 6.3 格式与类型问题

首次静态检查中：

- Ruff 要求整理 `re`/`ExperimentError` import；
- 三个文件需要机械换行/格式化；
- 一行超过 100 字符；
- strict mypy 对四个修改的 source 文件无问题。

处理方式是使用仓库 Ruff formatter/import fixer，没有关闭规则、加 noqa 或降低 strict mypy。

### 6.4 prepared schema 兼容断言

首轮完整 Gate 1 回归：

```text
3 failed, 127 passed in 264.01s
```

三个失败都来自旧测试把当前 prepared schema 硬编码为 4；实现实际返回 expected=5，且仍正确拒绝
历史 schema。没有回退实现版本，而是：

- 将当前 expected 更新为 5；
- 参数化补齐 schema v2/v3/v4 都必须保持只读失效；
- 保留真实历史 schema v1 bundle 的只读验证。

受影响复测：

```text
5 passed, 28 deselected in 9.36s
```

完整 Gate 1 相关集合随后为：

```text
132 passed in 263.74s
```

### 6.5 二次设计审视

首个 GREEN 版本为了兼容直接调用，允许 finalizer 在未给 expected arms 时从 observed summaries
推导计划。重新审视后认为这会留下绕过缺失-arm 检查的入口，因此在推送前移除回退，将
`expected_arms` 改成必需 keyword-only 参数，并同步全部 finalization 测试调用。

收紧后的最终化定向结果：

```text
16 passed in 13.91s
```

这项收紧并入同一个未推送 GREEN 提交，没有形成一个语义不独立的小提交。

## 7. 实际修改文件

| 文件 | 修改 |
|---|---|
| `scripts/gate1_evidence.py` | result schema v3、arm 合同校验、质量/采纳 flag 评估、aggregate 输出 |
| `scripts/gate1_prepared_evidence.py` | prepared schema v5，精确验证 result schema、quality policy 与 human-owned adoption 边界 |
| `scripts/gate1_finalization.py` | finalizer/validator 必须接收 expected arms，并按同一计划重算 aggregate |
| `scripts/run_load_test.py` | prepare 写入冻结策略；正式 finalization 传入启动前读取的 arm plan |
| `tests/unit/scripts/test_gate1_evidence.py` | 完整、缺失、无效、重复、unexpected 和负扩展合同 |
| `tests/unit/scripts/test_gate1_prepared_evidence.py` | 策略篡改与历史 schema v1–v4 只读合同 |
| `tests/unit/scripts/test_gate1_plots.py` | result schema v3、final aggregate gate flags、必需 expected arms |
| `tests/unit/scripts/test_experiment_scripts.py` | prepared manifest schema v5 和冻结 policy 输出合同 |

没有修改 app 领域代码、API、Compose、数据库模型或 Alembic migration。

## 8. 最终本地验证

| 检查 | 结果 | 状态 |
|---|---|---|
| RED | 缺少 `evaluate_gate1_gate_flags`，collection error | `VERIFIED_RED` |
| 首轮 GREEN 聚焦 | 18 passed | `VERIFIED` |
| schema 兼容修复聚焦 | 5 passed，28 deselected | `VERIFIED` |
| Gate 1 相关完整集合 | 132 passed | `VERIFIED` |
| finalization 收紧聚焦 | 16 passed | `VERIFIED` |
| 最终 SHA 非 integration 全量 | 463 passed，8 deselected，262.15s | `VERIFIED` |
| Ruff format | 250 files already formatted | `VERIFIED` |
| Ruff lint | All checks passed | `VERIFIED` |
| strict mypy | 117 source files，无问题 | `VERIFIED` |
| uv lock | 70 packages | `VERIFIED` |
| 本机真实 PostgreSQL/Redis、image、Compose | 本阶段本机未运行 | `NOT_RUN_LOCAL` |
| GitHub Actions Run #23 | 两个 job、真实服务、migration、image、Compose 与 hardening inspect success | `VERIFIED_REMOTE` |
| 正式 500-case/32-arm/soak | 未运行 | `NOT_RUN` |

### 8.1 远端验证

绑定文档头 `fa526f7ad6ada27ba5f9e6492afb5a8ab368b5a6` 的
[GitHub Actions Run #23](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30734753325)
最终为 `completed / success`。`quality-and-integration` 与 `compose-smoke` 两个 job 都成功。

步骤级结果确认实际执行并成功：

- lock、Ruff format/lint、strict mypy 和非 integration tests；
- Alembic upgrade；
- job claim/trace/lease fencing、blind review、tenant/dataset、artifact ownership、跨表 tenant
  constraint、readiness、Redis event isolation 和 Run idempotency 的真实服务 integration；
- P2 migration downgrade/re-upgrade；
- application image build；
- 完整 Compose topology build、fresh PostgreSQL/Redis、Compose migration、API/Worker/Reaper、
  readiness 和 effective container hardening inspect。

两个 failure-annotation step 因无失败而 skipped，这是 workflow 的预期条件分支，不是测试缺失。
Run #23 仍是普通 CI，不包含正式 500-case/32-arm，因此只把远端代码/服务合同提升为
`VERIFIED_REMOTE`，不改变 formal Gate 的 `NOT_RUN`。

## 9. 本次证明了什么

1. prepared bundle 机器可读地冻结不可弱化质量策略和预期 result schema；
2. 聚合器能区分完整有效、已知无效和缺失证据；
3. duplicate/unexpected/mismatched arm 不能被静默汇总；
4. finalizer 正式路径必须使用冻结 expected arm plan；
5. quality 通过只会开放人工评审，不会自动选择 Worker 或改变部署；
6. 负扩展被保留为结果，不会被删除或误报为实验基础设施失败；
7. 旧 prepared/result artifact 保持只读，不会被覆盖成新 schema。

## 10. 仍未证明什么

1. 没有运行正式 500-case/32-arm，因此没有任何吞吐、p95/p99、扩展拐点或容量结论；
2. 没有用户批准的数值 adoption policy，因此 adoption decision 明确为 `NOT_RUN`；
3. `READY_FOR_HUMAN_REVIEW` 不表示推荐某个 Worker 数；
4. 普通 CI 不能证明生产机器的资源余量、OOM/throttling 或数据库容量；
5. 当前 quality 输入依赖 per-arm `valid_for_capacity_comparison` 合同，未来新增必需证据时必须同步
   扩展该 flag 的 fail-closed 来源和 schema；
6. 本阶段没有解决 Worker 集群总资源聚合，P2-6 将单独处理；
7. 本阶段没有实现 transactional outbox，P2-7 将单独处理。

## 11. 对旧 prepared evidence 的影响

旧 prepared schema v1–v4 不能执行：

- schema v5 verifier 会返回 `MANIFEST_INVALID`；
- 关键执行脚本 SHA 也已变化；
- result schema 预期从 v2 变为 v3；
- 旧 bundle 没有冻结 quality policy。

正确做法是在最终干净 source commit 上重新运行 `--prepare-only`。禁止编辑旧 manifest、重算旧
hash 或覆盖历史目录来“升级”证据。

## 12. 回滚方案

如果新 gate evaluator 出现问题，按以下顺序回滚：

1. 停止任何尚未授权的正式 Gate；
2. 回滚 GREEN 提交 `3ee4480`；
3. 保留 RED 测试或同时回滚 `a9a1324`，取决于是否暂时撤销整个 P2-5 合同；
4. 不修改任何既有 `docs/results/`；
5. 重新 prepare，不能继续使用 schema v5 bundle 驱动旧 result writer。

没有 migration，因此不需要数据库 downgrade。回滚会恢复 prepared schema v4/result schema v2，
但也会重新暴露无自动 gate 评估的原始风险。

## 13. 学习与面试表述

推荐表述：

> 我把实验授权、客观质量检查和部署采纳拆成三个层次。prepared manifest 冻结不可弱化的
> expected-arm 质量策略；result schema v3 自动区分 VERIFIED、FAILED 和 UNKNOWN；只有质量
> 完整时才标记可进入人工评审，但系统始终不自动选择 Worker 数。这样既能机器检查证据完整性，
> 又不会用工具替人编造性能阈值。

不应表述为：

- “Gate 1 已经通过”；
- “系统自动找到了最佳 Worker 数”；
- “500-case 扩展性已经验证”；
- “负扩展会自动阻止部署”；
- “普通 CI 已证明生产容量”。
