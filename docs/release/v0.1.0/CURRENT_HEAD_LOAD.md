# v0.1.0 RC current-head formal load

结论：current fair scheduler 的正式 500-case/32-arm 协议本身 `VERIFIED`，但相对 historical
pre-fair baseline 的 release performance gate 失败。

## Current RC evidence

- source：`6acf72c3aa73c9fdc1664fe4e847fc8b8e90efd7`；
- Actions run：`31274490704`，`completed/success`；
- immutable bundle：`docs/results/load/gate1-gh-31274490704-1/`；
- artifact：`9026814020`，9,702,555 bytes；
- digest：`sha256:099c7dff5302c82c61efc69ff1ddb634225883c0dd657adf7f3a61756da01d93`；
- final manifest：32/32 arms、664 payload files，独立文件集/size/SHA-256 校验通过；
- 2 workloads × 4 worker counts × 4 repetitions × 500 jobs = 16,000 unique terminal successes；
- lost、failed、duplicate durable result、binding mismatch、collector gap 与 invalid arm 均为 0。

## Formal baseline comparison

Historical baseline 是 source `15e7ac2e28b70430acd0bff88ee6cc78e5b86a86`、run
`31177702100` 的 VERIFIED pre-fair 32-arm bundle。两者使用相同 workload、worker、repetition、
500-case、warm-up 和 seed 1729 协议。

| Workload | Workers | Pre-fair Jobs/s | Current fair RC Jobs/s | Change |
|---|---:|---:|---:|---:|
| io latency | 1 | 21.481 | 21.477 | -0.02% |
| io latency | 2 | 38.062 | 30.991 | -18.58% |
| io latency | 4 | 56.263 | 39.650 | -29.53% |
| io latency | 8 | 66.804 | 24.427 | -63.44% |
| transient 5% | 1 | 19.587 | 20.664 | +5.50% |
| transient 5% | 2 | 34.031 | 31.725 | -6.77% |
| transient 5% | 4 | 50.825 | 34.267 | -32.58% |
| transient 5% | 8 | 60.759 | 22.617 | -62.78% |

8 个主要 worker 组中 5 个回退超过 15%；组变化中位数 -24.05%，最差 -63.44%。32 个同名
repetition arm 的配对变化中位数 -29.55%，范围 -80.41% 至 +10.84%。current run 内部 4→8
也负扩展：io -15.22%，transient -11.65%。

pre-fair runner 为 4-vCPU AMD EPYC 7763，current runner 为 4-vCPU AMD EPYC 9V74；这些百分比
不能外推为生产 SLO或严格的纯 scheduler 因果效应。不过相同协议的两个 workload 都在 4/8 workers
显著回退，且 current snapshot 自身发生负扩展，已足够触发本次 fail-closed release gate。

## 允许与禁止的表述

可以说：current fair 32-arm protocol 32/32 VERIFIED、16,000 jobs 无 correctness failure，并如实给出
上述吞吐。不能说：v0.1.0 比旧版更快、8 workers 最佳、linear scaling、production-ready，或把旧
pre-fair 3.11× 扩展结果冒充 current fair scheduler。
