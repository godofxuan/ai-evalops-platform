# v0.1.0 release decision

## Decision: NOT_READY

截至 2026-08-09，本分支不应创建或发布 `v0.1.0` Release。

审阅入口：[Draft PR #1](https://github.com/godofxuan/ai-evalops-platform/pull/1)。Draft 状态表示证据可供
审阅，不表示满足 release gate。

| Gate | Result | Evidence |
|---|---|---|
| correctness | PASS | final A–I ×3 27/27，stale accepted 0，formal/capacity 无丢失或重复 |
| fairness | PASS | 20:1 secondary tenant position ≤2，全部 source-bound arms VERIFIED |
| current-head capacity | PASS scoped | 1k/10k/100k 32+16 arms VERIFIED；不代表 production SLO |
| CI | PASS | `31274490725`、`31275450358` success；本地 629 passed |
| evidence manifest | PASS | capacity、formal load、fault 均独立 fileset/size/SHA-256 验证 |
| README/evidence consistency | PASS after this change | 只引用最终 VERIFIED、source-bound 数字 |
| performance release gate | **FAIL** | 8 个主要 worker 组中 5 个相对 formal baseline 回退 >15% |

唯一 blocker：tenant-fair claim path 在 4/8 workers 下的吞吐与扩展性未达到本次 release gate。最差
组回退 -63.44%，current run 自身 4→8 也负扩展。没有 LLM judge、UI、SDK、Kafka、Temporal、
production tracing backend 均不是 blocker。

## What is ready

代码与证据适合作为 Draft PR 供审阅：多租户公平 correctness、resume-safe lease/fencing、短暂依赖
中断恢复、1k/10k/100k source-bound 容量与完整证据链都已建立。它可以称为
“evidence-backed experimental release candidate”，不能称为 production-ready、production-grade、
exactly-once、linear scaling 或 strong fairness SLO。

## Required next release action

不要在本轮继续调优或创建 tag。下一轮应先单独批准新的性能调查范围，以 4/8-worker claim contention
为新假设建立 RED、最小修改与同环境 paired benchmark；只有 formal gate 重跑通过，才能把本文件
改为 `READY_FOR_V0_1_0_RELEASE`。历史 FAILED/negative bundles 必须继续保留。
