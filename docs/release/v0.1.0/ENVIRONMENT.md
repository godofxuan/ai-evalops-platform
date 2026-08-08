# v0.1.0 RC environment and reproducibility

真实 PostgreSQL/Redis/Compose 实验运行在 GitHub-hosted Linux runner；本机没有把 skipped integration
当作通过。三个最终协议的 runner 都记录为 4 logical CPU、AMD EPYC 9V74、约 16.77 GB RAM、
Linux 6.17.0-1020-azure、Docker 28.0.4、Compose 2.38.2、Python 3.12.13。

| Protocol | Run | Source | Runner CPU |
|---|---:|---|---|
| 1k/10k/100k fair capacity | `31272789199` | `9987a28…` | AMD EPYC 9V74, 4 vCPU |
| current formal 32-arm | `31274490704` | `6acf72c…` | AMD EPYC 9V74, 4 vCPU |
| final A–I ×3 fault | `31275450353` | `70a9b2b…` | AMD EPYC 9V74, 4 vCPU |

每个 bundle 保留 `runner.txt`、`source.txt`、`compose-ps.txt` 与有界 `compose.log`。Compose 日志保存
策略为最多末尾 10 MiB，并在 `compose-log-policy.txt` 记录原始字节数、保留字节数和命令退出码；
实验 raw/final manifest payload 不因日志裁剪而改写。artifact digest 提供 GitHub 上传对象身份，Git
内 manifest 则逐文件绑定内容。

Historical pre-fair formal baseline 使用 AMD EPYC 7763，而 current formal run 使用 EPYC 9V74；
因此跨 run 性能百分比只用于本次 release gate，不是跨硬件性能 SLO。容量优化前后的 RC paired
run `31266366590` 与 `31272789199` 恰好都使用 EPYC 9V74，可支持“物化显著改善当前 fair SQL”
这一较窄结论。

本机完整非集成验证为 Ruff format 318 files、Ruff all passed、MyPy 133 source files、pytest
629 passed / 13 skipped / 3 Windows temp-cleanup warnings。真实数据库、Redis、migration、image 与
Compose 路径由 GitHub CI `31274490725` 和 `31275450358` 覆盖。加入最终 evidence/docs 后的封版
复核为 Ruff format 325 files、Ruff all passed、MyPy 133 source files，以及 73 个 release/evidence/
claiming/workflow 聚焦测试通过（1 个相同类型的 Windows temp-cleanup warning）。
