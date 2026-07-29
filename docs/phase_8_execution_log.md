# Phase 8 逐步执行日志

日期：2026-07-29

起始提交：`e944c53`

实现提交：`c487f78`

## 1. 开始前判断

人工评审的难点不是 CRUD，而是身份、盲化和不可变证据：

- 普通 service key 不能提交“人工”标签；
- Reviewer A/B 必须不同；
- 两人不能看到 machine score 或对方标签；
- 第三人裁决不能覆盖原提交；
- agreement 与 adjudicated label 是不同概念。

决定新增 `can_review`，默认 false，只从数据库认证记录进入 Principal。它是管理员授予凭据的
信任边界，不被夸大为自然人证明。

## 2. Tracer 1：agreement/kappa

RED：`app.reviews` 不存在。

GREEN：

- exact agreement；
- reviewer marginal expected agreement；
- Cohen’s kappa；
- 单类别导致分母为零时返回 null。

结果：2 passed。

## 3. Tracer 2：认证权限派生

先修改 valid authentication test，要求 APIKeyCandidate.can_review=true 最终出现在 Principal。

RED：

```text
APIKeyCandidate.__init__() got an unexpected keyword argument 'can_review'
```

实现：

- APIKey ORM can_review default/server_default false；
- candidate/repository/authenticate/Principal 传递；
- CLI `--human-reviewer`；
- 旧测试候选使用默认 false，不扩大权限。

认证目标：9 passed。

## 4. Tracer 3：三张历史表和 migration

RED：无法 import HumanReviewTask/Submission/Adjudication。

新增 migration 0007：

- api_keys.can_review；
- Artifact type human_review_packet；
- 三张 tenant-owned review 表；
- Task run/case unique；
- Submission task/reviewer unique；
- Adjudication task unique；
- FK、index、status check。

ORM/auth 目标累计 14 passed，offline SQL head 0007。

## 5. Tracer 4：服务规则

测试先要求：

- ordinary Principal 在触碰 session 前抛 ReviewPermissionError；
- 第二份完整 labels 相同为 agreed，不同为 disputed。

RED 为 reviews.schemas 不存在。最小实现后 4 passed。

## 6. Tracer 5：HTTP blind response

先通过 fake service 固定公开响应：

- candidate answer 可见；
- own_submission；
- 没有 metrics/machine_score/reviewer_id/other_submission。

RED 是 404 route not found；加入 review router 后 GREEN。

## 7. Tracer 6：SQL 盲化

编译 PostgreSQL SQL 并验证：

- candidate query 有 tenant/run；
- candidate SELECT 不含 metrics_json；
- task list join 带当前 reviewer_id；
- task query带 tenant。

随后实现完整 service：

- deterministic sampling；
- blinded packet；
- immutable submission；
- second-review resolution；
- third reviewer adjudication；
- aggregate agreement；
-安全 AuditEvent。

## 8. 静态检查修正

目标测试 20 passed 后，Ruff/mypy 指出：

- import 排序；
- Hashable 应从 collections.abc；
- outer join Optional 与 SQLAlchemy stub 不一致；
- list invariance；
- JSONB evidence 类型为 object。

修正：

- agreement 接受 Sequence；
- builder 返回通用 Select；
- evidence 仅 list 才进入 packet；
- 未关闭 strict mypy。

## 9. Tracer 7：并发串行点

审查发现 task/reviewer unique 不能阻止第三个不同 reviewer 并发写入。新增 RED SQL builder
测试，要求 tenant-scoped Task `FOR UPDATE`。Submission 与 Adjudication 共用它，再检查数量/
状态。

## 10. Tracer 8：packet artifact

发现 migration 已声明 human_review_packet type，但运行路径未生成。新增序列化 RED：

- 必须含 run_id/candidate；
- 不得含 metrics/submission/reviewer。

GREEN 后生产 create_tasks：

- Task transaction 先提交；
- deterministic packet JSON 写内容寻址 store；
- 写 Run-owned Artifact metadata；
- 重试复用相同 digest。

## 11. 真实服务合同

新增 integration test，使用：

- 一个 ordinary creator key；
- Reviewer A/B；
- 第三 adjudicator；
- 两个 succeeded CaseResult。

合同验证：

- ordinary submit 403；
- packet 无 machine score；
- 两 reviewer 分别提交；
- agreed + disputed；
- overwrite 409；
- list 只含 own submission；
- 原 reviewer adjudicate 409；
- 第三 reviewer 201；
- aggregate metrics；
- packet artifact metadata。

本机环境未启用真实 PostgreSQL，因此该测试 skipped。

## 12. 最终验证

| 检查 | 结果 |
|---|---|
| lock | 48 packages，检查通过 |
| Ruff format/check | 通过 |
| mypy app+scripts | app 86 source files，无问题 |
| 非集成全量 | 210 passed，6 deselected |
| 真实 PostgreSQL human review | 1 skipped |
| Alembic | 唯一 head `20260729_0007`；offline SQL 通过 |

## 13. 能证明与不能证明

能证明代码/SQL 合同：

- reviewer permission 服务端派生；
- 双人 distinct、immutable；
- blind query/response/artifact；
- Task lock 串行点；
- third-person adjudication；
- agreement/kappa 公式。

不能证明：

- key 背后一定是自然人；
- 本机真实数据库并发成功；
- reviewer 培训质量、标注一致性足够；
- sampling 统计代表性；
- 生产级凭据分发和审计认证。
