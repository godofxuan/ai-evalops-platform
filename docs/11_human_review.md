# 双人盲评与裁决合同

## 身份信任边界

API Key 有两个服务端权限，均默认 false：

- `can_create_review_tasks`：创建或扩展 Task；
- `can_review`：reviewer list/submit/adjudicate。

建议管理员创建相互独立的 credential：

```bash
uv run python -m scripts.create_dev_api_key \
  --tenant-slug demo \
  --key-name review-operator \
  --review-task-creator

uv run python -m scripts.create_dev_api_key \
  --tenant-slug demo \
  --key-name reviewer-a \
  --human-reviewer
```

认证链从数据库 APIKey 记录派生两个 Principal capability。请求体、query 和 header 都不能
自行提权。管理员可以显式给同一 key 两种权限，但系统不自动联动，组织流程应优先分离。

这能保证：

- Worker 和普通 service key 不能调用 submission/adjudication；
- 普通 key 和 reviewer-only key 不能创建/扩展 Task；
- creator-only key 不能 list/submit/adjudicate；
- 两份 submission 来自不同 reviewer key；
- adjudicator 必须是第三个 reviewer key。

这不能从技术上证明持 key 的操作者一定是自然人。管理员仍需把 reviewer credential 只发给
真人并管理设备/组织流程。系统不声称生物识别、反自动化认证或“AI 绝不可能获得该 key”。

## 数据模型

`human_review_tasks`

- tenant/run/job/case；
- blinded packet JSON；
- open/agreed/disputed/adjudicated；
- created_by；
- `(run_id, case_id)` 唯一。

`human_review_submissions`

- tenant/task/reviewer；
- labels JSON；
- optional comment；
- `(task_id, reviewer_id)` 唯一；
- 只有 INSERT API，没有 UPDATE/DELETE API。

`human_review_adjudications`

- tenant/task/adjudicator；
- final labels 和 rationale；
- task 唯一；
- 只有 disputed task 可以创建。

自动 `CaseResult.metrics_json` 与人工 labels 保存在不同表中。

## Task 生成和盲化

接口：

```text
POST /api/v1/runs/{run_id}/review-tasks
```

必须使用 `can_create_review_tasks=true` 的 key。权限检查发生在 Run 查询、Task transaction 和
artifact 写入之前；失败返回 403 `review_task_creator_required`。这与 reviewer 失败的
`human_reviewer_required` 明确区分。

候选仅来自 tenant-owned Run 的 succeeded Job/CaseResult。sample 使用
`sha256(run_id:case_id)` deterministic 排序，便于相同 Run 的重试复现。

packet 只含：

- case_id；
- question；
- reference answer；
- candidate answer；
- citations；
- sources。

候选 SQL 不选择 `metrics_json`。生成的 `human_review_packet` artifact 也只序列化 packet，
不含 machine score、reviewer、submission 或 adjudication。

当前 Task insert 和文件系统 artifact 不是分布式原子事务：Task 先提交，artifact 失败时同一
创建请求可重试补齐。这避免在数据库事务中进行文件 I/O，但意味着必须监控 artifact 生成失败。

## Reviewer 读取

接口：

```text
GET /api/v1/review-tasks?run_id=...
```

必须使用 `can_review=true` 的 key。SQL outer join Submission 时附加：

```text
submission.reviewer_id = principal.api_key_id
```

响应只含 `own_submission`，不返回另一 reviewer 的 identity/labels。即使 Task 已 disputed，
Reviewer A 也只看自己的原始提交。

## Submission

接口：

```text
POST /api/v1/review-tasks/{task_id}/submissions
```

事务：

1. tenant-scoped `SELECT task ... FOR UPDATE`；
2. 要求 Task=open；
3. 拒绝同一 reviewer 重复；
4. 拒绝已有两份 submission；
5. INSERT immutable submission；
6. 第二份到达时比较完整 labels；
7. 相同：agreed；不同：disputed；
8. 写不含 labels 内容的 AuditEvent。

Task row 是所有 reviewer 的串行点，避免三个不同 reviewer 并发绕过“最多两份”的应用检查。
数据库 unique 另行保护同一 reviewer 重复。

## Adjudication

接口：

```text
POST /api/v1/review-tasks/{task_id}/adjudication
```

要求：

- Task=disputed；
- 已有恰好两个不同 reviewer；
- adjudicator 不在两位 reviewer 中；
- task 尚无 adjudication；
- 写 final labels+rationale，Task 变 adjudicated；
- 原 submissions 不修改。

## Agreement 与 Cohen’s kappa

接口：

```text
GET /api/v1/runs/{run_id}/review-metrics
```

只聚合恰好有两份 submission 的 Task。对两边都有非空评分的维度形成 label pairs。

```text
exact agreement = observed equal pairs / paired labels
kappa = (observed agreement - expected agreement)
        / (1 - expected agreement)
```

expected agreement 来自两位 reviewer 各自的边际类别分布。如果两人只使用同一个类别，
expected=1，分母为零，kappa 返回 null 而不是伪造 1.0。

Adjudication 不覆盖双评审 agreement/kappa；它是分歧后的最终业务标签，不应改写原始一致性
证据。

## 测试边界

单元/API 测试覆盖：

- agreement/kappa；
- ordinary key 在 DB 前被拒绝；
- agreed/disputed 状态；
- tenant/blind candidate SQL；
- own-submission join；
- Task `FOR UPDATE`；
- packet artifact 不含敏感评审字段；
- HTTP blind response。

真实 PostgreSQL integration 合同覆盖普通 key 403、两个 reviewer、不可覆盖、第三人裁决、
packet artifact 和 metrics。本机没有启用 migrated PostgreSQL，结果 skipped，不能写成通过。
