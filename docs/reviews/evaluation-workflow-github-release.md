# 2026-09-12 GitHub 推送与 CI 诊断追加记录

本文件是本地交付之后的追加记录，不覆盖此前 ZIP、旧失败或旧 CODE/DOC 结论。用户本次明确授权核对指标后推送 GitHub。仅操作 `godofxuan/ai-evalops-platform` 的 `codex/evaluation-workflow-v1`，不推 main、不合并、不部署。

## 已核对的提升

- 输出异常、已有锁、写失败、无效 SHA 的实际 2 题×2 臂回环 HTTP 反例：不必要的目标请求 4 次降到 0 次。不是生产 QPS 或账单节省测量。
- 64 题长响应诊断超限仍保留源结果；执行后导出失败可离线恢复，恢复不调用目标。磁盘完全不能写时不保证捕获成功。
- 合成 SDK 演示 120 题 / 240 观察全部关联，480 个投影 span。不是实际 Agent 内部轨迹或业务效果提升。
- 全量本地非集成 1401 passed；空白复核 240 null / 0 paired。没有真实模型正确率或人工一致率提升证据。

## 首次推送与失败

正常推送完整 HEAD `24b78e329c057fac85de56a5e1797e2bec59719d`，远端 `ls-remote` 精确匹配。该提交包含本轮评测实现 CODE `d0ced60cc64c19876fac10608b1c4cf54676e18c` 及后续文档。

对应 [CI 34694130509](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34694130509) 的 Compose 任务在 `Build the complete current topology` 失败：Docker Hub 的 `minio/minio:RELEASE.2025-09-07T16-13-09Z` 返回 pull access denied / insufficient_scope。应用尚未启动。此前本轮没有改 deploy 或 CI workflow，不能把它当新评测算法错误，也不能忽略失败写成全绿。

按 diagnose 流程先读取真实日志，然后列出三项可证伪假设：官方镜像可用性变化、运行器临时鉴权问题、配置引用错误。最小匿名注册表查询在本机也得到 Docker Hub 401；同版本官方 Quay 镜像返回 200，说明不只是该 CI runner 的临时问题。原始 CI 日志与注册表索引留存在本地 `artifacts/evaluation-workflow-20260912/github-ci-34694130509/`。

## 最小修复及范围

官方 [容器说明](https://github.com/minio/minio/blob/master/docs/docker/README.md) 使用 `quay.io/minio/minio`。实际获取同版本索引并计算 SHA256 为 `14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`；linux/amd64 子清单 `a1a8bd4ac40ad7881a245bab97323e18f971e4d4cba2c2007ec1bedd21cbaba2` 的配置标签 version/release 均为原版本，入口仍为 `/usr/bin/docker-entrypoint.sh`。

只修改 `deploy/minio/Dockerfile` 的镜像来源并固定摘要，保留版本、非 root 用户、数据目录、Compose 服务、安全限制和全部集成检查。没有使用第三方镜像，没有切换对象存储产品，没有降低测试门槛。Docker Hub 已不能读取旧清单，因此不声称两个注册表镜像字节已经交叉验证相同；这里只证明官方 Quay 同发布版本的确切内容。

先修改部署合同测试，旧 Dockerfile 下得到 1 failed（红灯）；再修改 Dockerfile。这个测试只防止配置退回旧来源，不是实际容器运行证明。真实拉取、构建、MinIO/S3 和 Compose 运行必须由新提交对应 CI 决定；本机没有 Docker，不伪造本地容器通过。

修复后的部署配置和加固验证集合为 21 passed / 0.39 秒，Ruff 格式及 lint 通过，历史证据 manifest 复验通过；红/绿 JUnit 分别保留为 `minio-registry-red.xml` 与 `minio-registry-green.xml`。运行代码、gold 和质量门槛没有变化。

这不是 MinIO 安全升级。官方仓库现已归档并说明不再维护（见 [官方 README](https://github.com/minio/minio)）；保留该历史版本用于现有开发/集成验证，不据此宣称生产存储选型或漏洞问题已解决。未来生产使用需要单独的支持和安全评估，不在本轮偷偷替换依赖体系。

## 版本与证据解释

后续镜像修复提交会成为新的远端 HEAD；不要把首次 `24b78e3` 的失败 CI 当作后续 HEAD 的结果。最终精确 HEAD、run URL、成功/失败和脱敏证据以 GitHub Actions 与本地追加收据为准。旧交付 ZIP 保留其原身份和“推送前”状态，不原地改写。
