# 持久实验客户端：提交后可以退出，再用 ID 恢复

本页对应 `scripts.product_experiment_client`，不是本地一次性 `run_product_experiment`。当前实现仅支持 DEMO；工程运行成功不会自动获得正式质量或生产资格。阶段验证进度见 [执行记录](reviews/trustworthy-product-execution-log.md)。

## 前置条件

- 服务端 PostgreSQL 已迁移至 0033，API、既有 worker、Redis 和 artifact store 可用。
- 管理者显式启用 `EVALOPS_PRODUCT_EXPERIMENT_SUBMISSION_ENABLED` 并配置 `EVALOPS_PRODUCT_EXECUTION_CODE_SHA`；两组 HTTP 目标必须预先注册。客户端不能提供任意被测 URL 或目标令牌。
- 使用当前租户的 API key，放入环境变量 `EVALOPS_API_KEY`，不写进命令参数、请求文件或 Git。客户端 API 地址通常用 HTTPS；仅本机 localhost/127.0.0.1/::1 支持 HTTP。
- `request.json` 使用 `evalops.durable-experiment-request/1.0`，不是 local experiment spec。合同可在 API `/docs` 查看；包括 dataset_version_id、原始 JSON 的 source_dataset_sha256、两组 registered target ID/version、来源声明、固定 policy 和预算。
- dataset_version_id 必须属于当前租户，指向 `map_product_dataset` 产生的规范化 JSONL 版本。通过既有 `POST /api/v1/datasets` 创建数据集，再通过 `POST /api/v1/datasets/{id}/versions` 的 `file` multipart 字段上传规范化内容（application/jsonl）。原始 `cases.json` 的 SHA 与规范化 JSONL 的 SHA 不同，不能互换。原始数据应受控保存；此 CLI 暂不自动创建/上传数据集。

## 提交、恢复与取消

下面的 `$apiUrl`、`$experimentId` 应替换为你的实际服务地址和提交响应中的 UUID。所有全局参数放在子命令前。

```powershell
python -m scripts.product_experiment_client --api-url $apiUrl submit --request request.json --dataset cases.json --idempotency-key stable-pair-001
python -m scripts.product_experiment_client --api-url $apiUrl get $experimentId
python -m scripts.product_experiment_client --api-url $apiUrl wait $experimentId --wait-seconds 300 --poll-seconds 2
python -m scripts.product_experiment_client --api-url $apiUrl cancel $experimentId
```

提交返回父实验 UUID、两组 Run UUID 和 status_url。发生网络中断且不确定提交是否成功时，用**完全相同的 request、原始数据和幂等键**重新提交；不要换键假装是恢复。不自动重试非幂等的数据集创建。

关闭客户端或 wait 超时不会取消服务器任务。需要取消时明确运行 cancel；取消不保证撤销目标服务已经产生的外部副作用。wait 返回 READY_FOR_ASSESSMENT 只表示执行完毕，可以生成评估报告。

## 默认公共导出与私有完整证据

```powershell
python -m scripts.product_experiment_client --api-url $apiUrl export $experimentId --output-dir artifacts/my-public-report
python -m scripts.product_experiment_client --api-url $apiUrl export $experimentId --include-private --dataset cases.json --output-dir artifacts/my-private-report
```

输出目录必须不存在；绝不覆盖已有目录。每个包包含 report.json、report.html、manifest.json；私有包额外保存原始 dataset.json。report.json 保留服务器发布的精确字节，不重新格式化后冒充原 artifact SHA。写入临时目录、完整校验后再原子发布；另一个 writer 的锁不会被自动删除，强杀遗留锁需人工确认对应进程已经结束后处理。

公共模式只有允许字段摘要，不保存逐题答案。私有模式必须显式提供原始数据，验证器据此重算整个报告；不能从报告答案反造一份“原始输入”。本轮不增加原始数据下载端点，避免为了客户端便利扩大私密材料的读取接口。私有目录不得直接放入公开仓库。

## 离线复核

```powershell
python -m scripts.product_experiment_client verify artifacts/my-private-report
python -m scripts.product_experiment_client verify artifacts/my-private-report --expected-report-sha256 $trustedReportSha
```

无需 API、密钥或目标服务。目录只能包含该可见性要求的固定文件集合，拒绝符号链接/junction、未知文件、缺文件、重复 JSON 字段和 hash/大小不符。HTML 必须能由报告重新生成；即使篡改 HTML 后重算 manifest hash，也会被拒绝。

- PUBLIC_PROJECTION_ONLY：仅验证公开摘要与派生 HTML，不声称复核了私有证据。
- PRIVATE_RECOMPUTED：用原始输入、结果快照和共享聚合器重算内容一致；仍不是来源认证、人工审核或真实模型质量提升证明。
- 库级单报告校验缺原始材料时返回 PRIVATE_SOURCE_REQUIRED；完整私有包不会接受这种状态。

包里的摘要只能证明内容自洽；独立来源的 `--expected-report-sha256` 才提供外部字节锚点。公开报告里的 private_report_sha256 指向私有报告整体字节；summary.private_result_sha256 指向内层规范化 result，不能混用。

## 退出码与预算

submit/get/cancel/wait 返回 0 表示操作成功，不是质量通过。wait 超时为 4，客户端中断为 130。verify 返回 0 表示证据完整性验证成功，即使报告质量状态为 INSUFFICIENT_EVIDENCE；输出会同时明确 quality_status。

export 沿用本地产品质量门禁：自动门禁通过为 0，质量失败为 1，缺输入/证据不足为 2，执行失败为 3。`--gate formal` 不会让 DEMO_PASS 获得正式通过。导出返回 2 时证据目录可能已经正确生成，应先查看 JSON 输出，不要直接重跑实验。

请求文件限 1 MiB，原始数据限 10 MiB。SDK 响应默认 2 MiB；CLI `--max-response-mib` 默认 32，可在 1–512 之间调整。请求总时间 `--request-timeout` 默认 30 秒、最大 300 秒，包括响应流读取；不承诺可抢占的统计 CPU 或部署级 RSS 限额。输出错误不回显上游正文或凭据。

真实客户端 HTTP 测试、真实数据库集成、worker 实际网络与进程故障恢复是不同层级；本页不是 S5/S7 最终验收完成声明。
