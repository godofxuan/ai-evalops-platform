# 4→8 Worker scaling 百分比证据修正

## 1. 修正范围

本次只修正 release-facing 文档对 current fair formal load 的 4→8 Worker 自扩展百分比解释，
不修改 `docs/results/load/gate1-gh-31274490704-1/` 下任何 immutable raw、summary、manifest、
plot 或负面结果。

## 2. 原错误与根因

旧文档写成：

- io latency：`-15.22%`；
- transient 5%：`-11.65%`。

`final/summary/aggregate.json` 中的字段名是 `median_throughput_change`，生成逻辑保存的是：

```text
current_median_jobs_per_second - previous_median_jobs_per_second
```

因此 raw 中的 `-15.22354692299188` 与 `-11.64943437387521` 单位都是 Jobs/s；它们是绝对
吞吐差值，不是百分比。文档读取时直接格式化为 `%`，造成单位错误。raw evidence 本身没有损坏，
也不应为了修正文档而被回写。

## 3. 正确算法与结果

新增并测试纯函数 `scripts.gate1_evidence.relative_change_percent`，公式为：

```text
relative change percent = (current / baseline - 1) × 100
```

测试直接使用 immutable aggregate 中的精确 4/8 Worker 中位数：

| Workload | 4 Worker baseline | 8 Worker current | Absolute delta | Correct relative change |
|---|---:|---:|---:|---:|
| io latency | 39.6504130226613 | 24.4268660996694 | -15.2235469229919 Jobs/s | -38.3944220563130% |
| transient 5% | 34.2668528741652 | 22.6174185002900 | -11.6494343738752 Jobs/s | -33.9962190769438% |

Release-facing 文档按两位小数展示为 `-38.39%` 与 `-34.00%`。

## 4. TDD 证据

RED：新增
`test_relative_change_percent_uses_baseline_as_denominator` 后，测试收集明确失败：
`ImportError: cannot import name 'relative_change_percent'`。

GREEN：实现最小纯函数后，同一测试 `1 passed`。随后还需运行完整
`tests/unit/scripts/test_gate1_evidence.py` 与相关 release evidence 测试，确保没有改变历史
aggregate schema 或 validator 的可重放性。

## 5. 对 release decision 的影响

结论方向不变：4→8 仍是负扩展，formal performance gate 仍失败，v0.1.0 仍为 `NOT_READY`。

但严重程度被旧文档低估：io 不是下降 15.22%，而是下降约 38.39%；transient 不是下降
11.65%，而是下降约 34.00%。因此该修正不会解除 blocker，反而强化“必须先定位并修复 fair
scheduler 并发瓶颈，再重新采集 source-bound evidence”的决定。
