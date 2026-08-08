# v0.1.0 RC fairness and capacity

结论：公平性与 current-head 1k/10k/100k 容量证据完整、source-bound 且 `VERIFIED`；这不等于
整个 release READY，正式 32-arm 性能门仍失败。

## 证据身份

- production source：`9987a28d707653a45fffa60a283461e2514e3103`；
- Actions run：`31272789199`，`completed/success`；
- immutable bundle：`docs/results/release/v0.1.0/rc-gh-31272789199-1/`；
- artifact：`9026479804`，1,115,908 bytes；
- artifact digest：`sha256:5727cd2275121cf19bf1960c6c971be8b5dfbead575d235989906e7b5e3ce97f`；
- initial：32/32 arms；large：16/16 arms；每个 fair/legacy EXPLAIN 各 4 次；
- admission：initial 与 large 均 `VERIFIED`，blockers 为空。

预期 arm 由固定协议生成，不是从观测 CSV 反推。独立 verifier 重算 manifest 文件集、字节数、
SHA-256、source/row source、arm 集合、EXPLAIN 覆盖、candidate cardinality、correctness 与 20:1
fairness，全部通过。

## 真实 worker 样本

每个 arm 在预置 backlog 中由真实 `EvaluationWorker` 完成 100 个 sample jobs；Jobs/s 不是排空整个
backlog 的吞吐。以下均为 16 个 arm 的 min / median / max：

| Queue | Jobs/s | Claim p95 ms | Fair plan ms | Legacy FIFO plan ms | Fair/legacy plan ratio median |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 11.150 / 43.240 / 68.043 | 12.151 / 93.428 / 1,626.119 | 1.765 / 2.493 / 55.475 | 2.227 / 3.132 / 38.896 | 0.846 |
| 10,000 | 4.849 / 22.501 / 31.047 | 22.946 / 159.997 / 3,600.526 | 13.748 / 20.376 / 31.930 | 25.372 / 37.072 / 45.018 | 0.613 |
| 100,000 | 0.628 / 3.377 / 5.488 | 164.639 / 1,240.834 / 41,386.537 | 159.839 / 183.717 / 359.116 | 316.185 / 357.850 / 1,456.750 | 0.491 |

100k 的 16 个 paired plan ratio 范围是 0.247–0.770，没有 arm 超过 release investigation 的
3× 门槛。1k 有一个单租户 w1 plan ratio 16.254；它被保留为局部异常，不能用整体中位数掩盖。
运行时只实测 current fair worker；legacy FIFO 对照是同 fixture、同 `REPEATABLE READ` snapshot 的
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`，不能写成两套 worker 的端到端 latency A/B。

## 公平性与正确性

- 20:1 skew 的每个 fair arm 首个 secondary tenant 均在位置 1 或 2；
- legacy FIFO 对照的 secondary tenant 均晚于位置 2；
- submitted、unique、terminal 均相等；
- lost、duplicate durable result、stale accepted、illegal transition、orphan、attempt mismatch 均为 0；
- candidate cardinality 在 fair/legacy 的 384 份 EXPLAIN 中与 1k/10k/100k 队列严格一致。

## 已做的最小优化与限制

原 fair SQL 会对完整候选集做 WindowAgg/join/sort。依据 100k raw plan，只做了两项同一假设下的
最小 SQL 形状修正：先过滤 `tenant_candidate_rank <= limit`，再把 ranked CTE 标记
`MATERIALIZED`，防止 PostgreSQL 把窗口子查询内联后按外层 join 重复执行。lease、heartbeat、
Tenant→Run→Job 锁序、`FOR UPDATE SKIP LOCKED`、eligibility recheck 和 fencing 均未改变。

最严重限制仍是 100k 热点租户高并发：single-tenant/w8 的 claim p95 为 41,386.537 ms、
contention retries 为 504、吞吐 0.628 Jobs/s。证据不支持 linear scaling、强公平 SLO 或
production capacity SLO。
