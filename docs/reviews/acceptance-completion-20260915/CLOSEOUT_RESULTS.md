# 遗漏验收项补齐结果

## 版本与范围

- 基线 DOC：12b6ca495b03fd9fb67a3f987ee51c5b37ada0ac。
- 新 CODE：60773c648923f6cd2118da0e4ebc264644151274。
- 初始候选：6a9360c8d745066bed09b301344b80667ae8c223，其集成失败日志保留，不作为最终通过版本。
- 分支：codex/audit-remediation-20260915，正常推送；没有修改 main、RAG 或已投递历史链接。
- 最终 DOC 是包含本记录的文档提交，精确身份由交付包 DELIVERY_MANIFEST.json 和外部交付回执记录，避免在文档内自引用尚不存在的提交SHA。
- 本轮仅补完整验收、监控与回归中发现的幂等缺陷；模型调用0，无新框架、数据库产品、部署或生产认证。

## 实际完成的改动

1. 现有worker/reaper使用同一个进程级registry记录租约授权/拒绝原因、锁查询耗时、已提交回收的到期延迟；使用固定低基数标签，不记录题目或身份标签，不增加SQL取样或监控数据库。真实锁等待、跨过期、回滚、重复扫描和HTTP scrape均有回归。
2. 冻结0–99种子的真实PG并发测试：四种场景各25轮、合计750个初始actor，覆盖心跳、双结果、失败、取消、双回收和恢复。核对终态、attempt、唯一接纳和Outbox，不吞掉异常，不重试到通过。
3. 专门Windows CI实际运行文件/目录symlink与junction共5个案例。门禁拒绝跳过、缺项、重复或失败；本机缺权限的3个skip原样保留，不通过修改系统权限绕过。
4. CI合成报告与随机记录绑定当前提交，不再使用测试占位SHA。CODE与DOC分别查精确CI，不能借旧绿色结果。
5. 完整集成暴露内容寻址冷插入的第二唯一键竞态。真实50组×8路先复现，最小修复冲突仲裁后仍严格核对摘要、路径、大小和生命周期；不同内容抢占路径的负控继续拒绝。
   随后Linux的10个随机种子暴露取消路径的ORM旧状态问题：相同Run产生两条完成事件。新增真实PG屏障在本机稳定复现，锁定查询强制刷新identity map后，同一测试只产生一条事件且不错误标记取消；不靠删除事件或放宽随机断言处理。
6. 新版本直接跑QA/Agent演示、local重算和durable公有/私有离线验证；补齐可操作练习、简历稿与答辩说明。工程验收与用户是否已经亲自练习分开记录。

## 新 CODE 的本地验证

测试在干净detached worktree 60773c6运行，Python3.12.13、uv.lock锁定依赖；独立PostgreSQL18.6/Redis8.8.1，迁移至0033。本机不具备MinIO/Docker验收环境。表格中的分组有重叠，不能相加当作独立覆盖率。最终日志位于交付包evidence/verified-60773c6；candidate-evidence中的final-*是旧候选ce7c088的原始文件名，不能替换最终版本。

| 验证 | 实际结果 | 证据 |
| --- | --- | --- |
| 全部非integration测试 | 1520 passed / 3 Windows权限skip，451.14秒 | unit.log/xml |
| 全部integration测试 | 179 passed / 3 MinIO skip，373.68秒 | integration.log/xml |
| 100固定seed | 100 passed，seed集合恰为0–99，全部绑定新CODE | diagnostics/lock-diagnostics.jsonl、concurrency-receipt.json |
| 冷内容并发登记 | 50组×8次，共400次，50组无非预期异常；另有路径身份冲突负控 | 同一完整集成JUnit及50条cold-blob记录 |
| 固定上游checker发行门禁 | 37 passed / 0 skipped | release.log/xml、固定材料manifest/license |
| 静态检查 | ruff、format、mypy 259文件通过；依赖锁未变 | lint/format/types.log |
| durable私有验证 | PRIVATE_RECOMPUTED，quality=EXECUTION_FAILED | private-verify.log |
| durable公有验证 | PUBLIC_PROJECTION_ONLY，同一负结果 | public-verify.log |
| QA/Agent演示及QA analyze | 执行成功；LOCAL_RECOMPUTED_NOT_PROVENANCE，DEMO_PASS | demo-*.log及新目录产物 |

固定20×2故障矩阵再次得到40计划、24唯一接纳、12失败、4取消、39次attempt/HTTP call。这里任务质量失败是预设故障结果；平台正确性验收通过不应把它改写为质量PASS。

## 远端 CI

旧候选ce7c088的CI [34945618819](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34945618819)失败：随机90 passed/10 failed；Windows和Compose通过。已保留其原始归档，不对该提交重复挑绿。

新CODE CI：[34947385076](https://github.com/godofxuan/ai-evalops-platform/actions/runs/34947385076)，必须按完整40位SHA核验。本文冻结时该运行的100seed步骤、Windows和Compose已成功，其余完整集成尚在执行，因此不预写整轮成功。文档不再改变代码，其独立CI可与CODE剩余步骤并行；只有两次完整CI均成功后才允许最终交付。

精确DOC、两次CI的最终状态、原始JUnit统计、下载产物摘要以及离线重算回执统一保存在交付包evidence/ci及外部FINAL_HANDOFF。GitHub审核应同时查看该固定CODE Run和文档提交自身的Checks，不用main或其他分支替代。验证脚本会拒绝错误SHA、缺失/跳过的必需测试、丢失seed或篡改ZIP；以机器回执定义交付时实际状态，避免自引用SHA及CI状态循环修改。

## 失败保留与边界

PLAN_AND_LOG.md逐步记录why、red/green、环境错误和修复效果。保留初始全套失败、冷写入red、本机Windows权限失败、遗漏Redis变量和测试tombstone残留，不把环境准备错误算作产品反例，也不删掉失败轮次。

指标是实际运行路径的可观测性，不是长期生产SLO或纯服务器锁等待。100个seed和400次冷写入是有界正确性测试，不是QPS、模型准确率或无死锁证明。没有正式质量A/B、人评、Shadow或生产负载资格；旧调度NEGATIVE_SCALING没有被本轮抵消。历史scorecard仍明确production NOT_VERIFIED，不能因为这轮可靠性修复就宣布生产晋级。

用户本人尚未完成练习，这不再作为拖延工程交付的借口。可运行路径见METRICS_AND_HANDS_ON.md；简历与教学增补见RESUME_AND_LEARNING_UPDATE.md。满足本轮工程验收后冻结功能，外部限制保持明示。
