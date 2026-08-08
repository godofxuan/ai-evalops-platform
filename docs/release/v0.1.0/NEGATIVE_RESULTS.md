# v0.1.0 RC negative results

失败与负面证据不删除、不改写为成功。它们解释为什么最终结论是 `NOT_READY`，也记录哪些方向已被
数据否定。

## Release blocker

最终 current fair formal run 虽然 32/32 完整且 correctness 通过，但相对 pre-fair baseline 的
8 个主要 worker 组有 5 个吞吐中位数回退超过 15%；4/8 workers 的回退分别达到约 30–63%。这是
唯一 release blocker。

## 保留的失败与中间结果

- `rc-gh-31265533928-1`：真实 100k 执行暴露 lease 计时起点问题；失败包保留。最小修复把 claim
  transaction 成功后才开始计算 execution lease，不放宽 fencing 或 lease 长度。
- `rc-gh-31266366590-1`：首个完整 1k/10k/100k fair bundle，全部 VERIFIED，但 100k fair/legacy
  plan ratio 中位数 3.087，证据指向全候选 WindowAgg/join/sort。
- `gate1-gh-31269813705-1`：32-arm 实验主体成功，Git 回写因 122,939,753-byte compose.log 超过
  GitHub 100 MiB 单文件限制失败；artifact 恢复、独立校验后裁剪外层诊断日志并保留原始身份。
- `rc-gh-31271973239-1`：rank predicate 后初始 32 arms 执行完成，但 evidence candidate cardinality
  对 PostgreSQL WindowAgg Run Condition 解释错误，assessment fail-closed 为 FAILED。
- `gate1-gh-31271973235-1`：rank predicate 未物化时，planner 内联造成窗口查询重复执行；正式
  32-arm 中 io 与 transient 都有 2→4、4→8 负扩展。该 bundle 由 artifact 恢复并保持完整。
- `fault-gh-31271973253-1`：同一中间 source 的 27/27 correctness 通过，但因并发机器人
  non-fast-forward 未能自动回写；artifact 恢复后独立校验并保留。

## 排除的误判

- workflow failure 不必然等于实验失败；必须看 execute、finalize、upload 与 Git 回写各步骤；
- `READY_FOR_HUMAN_REVIEW` 是 Gate 1 adoption 状态，不是 release READY；
- 1k/10k/100k plan 对照是同 snapshot EXPLAIN，不是两套 worker 的端到端 latency A/B；
- 本机 integration skip 不是通过；真实服务结果只引用成功的 GitHub Actions；
- 物化后容量 arm 相对优化前配对吞吐中位数 +65.25%，说明修改有效，但不抵消 formal baseline
  高并发 gate 的失败。

## 为什么不继续改生产代码

任务限制只允许一个假设、一个 RED/最小 production change、一次 paired benchmark。该闭环已经完成，
并重跑 10W/100J、20:1 fairness、fencing、large subset 与相关 32 arms。继续改 scheduler 会开启新的
未经授权优化周期。没有证据支持引入 Kafka、Celery、Temporal 或 Redis job queue。
