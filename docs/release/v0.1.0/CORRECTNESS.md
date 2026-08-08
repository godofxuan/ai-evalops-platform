# v0.1.0 RC correctness

结论：在本次定义的 correctness、fairness、lease/fencing 与短暂依赖中断协议内，没有发现回归。
这不等于 exactly-once、无限故障容忍或生产可靠性认证。

## Final fault evidence

- source：`70a9b2b9d6d4cd7f42d7fa9654771a64e6d707b6`；
- Actions run：`31275450353`，`completed/success`；
- immutable bundle：`docs/results/fault/fault-gh-31275450353-1/`；
- artifact：`9026907209`，147,158 bytes；
- digest：`sha256:30ff97585f4ac1ec433b87a79e7f364284517d850eb7efd7748f1c2b14d46531`；
- manifest：6/6 payload，独立 fileset/size/SHA-256 校验通过；
- report：A–I 各 3 次，共 27/27 records，`verified`。

| Invariant | Result |
|---|---:|
| lost jobs | 0 |
| duplicate CaseResult | 0 |
| duplicate terminal commit | 0 |
| orphan running | 0 |
| invariant failures | 0 |
| stale success attempted / accepted | 3 / 0 |
| stale failure attempted / accepted | 3 / 0 |

覆盖场景包括 claim 后杀 Worker、执行中 lease expiry、reclaim 后旧 Worker 晚到 success/failure、
Redis/PostgreSQL 3 秒中断、Worker restart、双 Reaper 竞争和重复 idempotency key。

## Capacity and formal-load cross-checks

最终 fair-capacity 48 arms（1k/10k/100k，每臂 100 sample jobs）全部满足
submitted=unique=terminal，lost/duplicate/stale accepted/illegal transition/orphan/attempt mismatch 为 0。
最终 formal load 的 32 arms、16,000 jobs 全部是 unique terminal success，collector gap 为 0。

production scheduler 的 rank 剪枝与 CTE materialization 没有改变 resume-safe claim：attempt/version、
lease owner/expiry、heartbeat、Tenant→Run→Job 锁序、stale result fencing 与 durable result commit
合同保持不变；最终 fault evidence 在修改后的 source 上再次通过。
