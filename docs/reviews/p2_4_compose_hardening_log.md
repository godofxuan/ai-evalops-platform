# P2-4 Compose 运行时边界加固：证据化实施日志

## 0. 阶段元数据

- 项目：AI EvalOps Platform。
- 阶段：P2-4，Compose non-root、read-only、capability、no-new-privileges 与资源上限。
- 起始分支：`codex/gate1-evidence-hardening`。
- 起始 SHA：`b0e637a4ec29ec538c1fdc257ac08fb634e0bd1f`。
- 实现提交：`6c84cd92257e5cbe7c4722e37c1acdfe7a9fa5fa`。
- 数据库 migration：无。
- 正式 500-case、32-arm、soak、破坏性故障注入：`NOT_RUN`。
- 阶段状态：`REMOTE_CI_VERIFIED / FORMAL_GATE_NOT_RUN`。

## 1. 指令适配性判断

本项是实际的纵深防御缺口，不只是 YAML 风格偏好。

原 `Dockerfile` 已创建 UID/GID 10001，并用 `USER 10001:10001` 运行应用镜像。这能保护直接使用
该镜像的默认场景，但 Compose 没有显式固定运行用户，也没有约束根文件系统、Linux
capability、setuid/setgid 提权和资源消耗。PostgreSQL 与 Redis 官方镜像的 entrypoint 还会先以
root 启动再降权。因此，单凭“Dockerfile 里有 USER”不能证明整套 Compose 拓扑都处于预期边界。

本项适合现在处理，原因是：

1. 六个服务及其写目录已经稳定，能够定义明确 allowlist；
2. 当前 CI 已有 fresh-volume Compose smoke，可验证数据库初始化兼容性；
3. 不需要改变领域模型、API、migration 或正式实验 schema；
4. 改动可以通过一次 Compose 配置回退完整撤销；
5. P2-5 之后的 Gate 自动化会依赖 Compose，先固定运行边界更合理。

本项不会被描述成“容器沙箱已经生产认证”。这些选项只能缩小容器内进程被利用后的能力和
资源爆炸半径，不能替代宿主机安全、rootless Docker、user namespace、seccomp/AppArmor 策略、
NetworkPolicy、secret manager 或生产容量测试。

## 2. 原始行为与证据位置

| 位置 | 原始行为 | 缺口 |
|---|---|---|
| `Dockerfile` | 应用镜像默认 `USER 10001:10001` | 只覆盖镜像默认值，不约束其他服务或 Compose override |
| `deploy/compose.yaml` 的 `x-app-service` | 共享 build、image、environment 和 artifact volume | 未显式 user/read_only/cap_drop/security_opt/resources |
| `postgres` | 官方镜像、命名 volume、loopback 端口 | entrypoint 可先以 root 启动；根 FS 与资源无限制 |
| `redis` | 官方镜像、AOF volume、loopback 端口 | 同样没有运行时最小权限或资源上限 |
| `migrate`、`reaper` | 继承共享 artifact volume | 两个角色不需要 artifact 写权限，却获得了写访问 |
| `.github/workflows/ci.yml` | 能 build/start/readiness | 没有检查 Docker 最终 HostConfig 是否真正应用安全项 |
| `tests/unit/test_deployment_config.py` | 只检查 HTTP Target Registry 环境变量 | 没有锁定任何容器边界 |

Docker Compose 官方规范明确提供 `user`、`read_only`、`cap_drop`、`security_opt`、`cpus`、
`mem_limit`、`pids_limit` 和带 `mode/uid/gid` 的 `tmpfs`。本阶段采用 service 级字段，而不是只写
Swarm `deploy.resources`，因为仓库实际使用的是普通 `docker compose`。

数据库镜像需要额外判断：

- PostgreSQL 官方 entrypoint 在 root 情况下修正 PGDATA 与 socket 目录 ownership，然后用
  `gosu postgres` 降权；官方实现也明确支持 `--user`；
- Redis 官方 entrypoint 在 root 情况下 chown 当前数据目录并用 `gosu redis` 降权，也明确支持
  `--user`；
- 本项目使用命名 volume，Docker 创建 volume 时会保留镜像挂载点的初始 ownership；
- 仍不能仅凭源码推断 fresh-volume 一定成功，所以必须让远端 Docker CI 实际创建并启动。

参考：

- [Docker Compose services 规范](https://docs.docker.com/reference/compose-file/services/)；
- [PostgreSQL 官方镜像 entrypoint](https://github.com/docker-library/postgres/blob/master/docker-entrypoint.sh)；
- [Redis 官方镜像 entrypoint](https://github.com/redis/docker-library-redis/blob/master/docker-entrypoint.sh)。

## 3. 风险

未加固时，一个被利用的进程会获得超出业务所需的默认容器能力，可以写镜像根文件系统，并可
在没有 CPU、内存或 PID 上限时拖垮整套开发/CI 主机。数据库 entrypoint 的短暂 root 阶段也比
“从第一个进程开始就是非 root”具有更大的攻击面。

直接粗暴加固也有可用性风险：

- read-only 根 FS 会让依赖 `/tmp` 或 PostgreSQL socket 的进程无法启动；
- 对仍需 chown 的 root entrypoint 执行 `cap_drop: ALL` 会使初始化失败；
- 硬编码数据库 UID/GID 会绑定具体基础镜像实现；
- 把数据 volume 也改成只读会破坏 PostgreSQL、Redis、Dataset/Artifact 正常写入；
- 过小的资源上限会引入 OOM、节流或连接/线程创建失败。

因此测试必须同时验证“限制存在”和“真实拓扑仍可启动”，二者缺一不可。

## 4. 冻结的最小合同

### 4.1 所有六个服务

`postgres`、`redis`、`migrate`、`api`、`worker`、`reaper` 必须同时满足：

- 显式非 root `user`；
- `read_only: true`；
- `cap_drop: [ALL]`；
- `security_opt: [no-new-privileges:true]`；
- 正数 CPU、memory 和 PID limit；
- 不能启用 privileged mode。

### 4.2 写路径 allowlist

- 所有应用角色只有 64 MiB、mode 1777 的 `/tmp` tmpfs；
- PostgreSQL 只写 `postgres_data:/var/lib/postgresql`，另有 `/tmp` 与
  `/var/run/postgresql` tmpfs；
- Redis 只写 `redis_data:/data`，另有 `/tmp` tmpfs；
- API 与 Worker 可写 `artifact_data:/data/artifacts`；
- migrate 与 Reaper 不再挂载 artifact volume。

这里的 read-only 指镜像根文件系统，不代表命名 volume 只读。数据库和 artifact 的业务写路径
仍然必须可写。

### 4.3 可调资源默认值

| 组 | CPU | memory | PID |
|---|---:|---:|---:|
| application roles | 1.0 | 512 MiB | 256 |
| PostgreSQL | 1.0 | 512 MiB | 256 |
| Redis | 0.5 | 256 MiB | 128 |

这些是开发/CI containment defaults，不是生产 sizing。`.env.example` 暴露九个
`EVALOPS_*` override，使用方必须用真实负载和 OOM/节流数据调参。

### 4.4 运行时证据

静态 YAML 解析通过仍不够。CI 必须对五个常驻容器执行 `docker inspect`，并验证：

- `Config.User` 非空、非 root，显式 group 时也不能是 root group；
- `HostConfig.ReadonlyRootfs is true`；
- `HostConfig.Privileged is false`；
- `HostConfig.CapDrop` 包含 `ALL`；
- `HostConfig.SecurityOpt` 启用 `no-new-privileges`；
- `Memory`、`NanoCpus`、`PidsLimit` 都大于零。

一次性 migrate 容器在运行后被 `--rm` 删除，因此由静态合同、实际 migration 成功和共用
`x-app-service` 三重覆盖，不在事后 inspect 列表中伪造一个不存在的容器。

## 5. 方案比较

### 方案 A：只加固应用服务

优点是数据库兼容风险最低。缺点是两个最有价值的数据进程仍可从 root entrypoint 启动，也没有
资源边界，不能满足“完整 Compose 拓扑”的问题定义。

### 方案 B：所有服务显式非 root，并为真实写目录提供 volume/tmpfs

优点是合同清晰、无需维护自定义数据库镜像，能用当前 CI 验证。风险是 named volume ownership
和官方镜像版本相关，必须用 fresh-volume smoke 锁定。

### 方案 C：为 PostgreSQL/Redis 维护自定义 wrapper 镜像

可以完全控制 UID、目录 ownership 和 entrypoint，但会增加镜像供应链、升级和补丁责任。当前
项目没有必须自定义数据库镜像的证据，成本高于收益。

选择方案 B。它是当前架构中最小、可审计、可回滚且能覆盖六个服务的方案。

## 6. RED → GREEN 记录

### 6.1 Compose 静态合同

先向 `tests/unit/test_deployment_config.py` 添加四组 RED：

1. 六个服务显式非 root user；
2. 六个服务 read-only、drop ALL、no-new-privileges；
3. 六个服务都有 CPU/memory/PID 上限，九个 override 在 `.env.example` 有记录；
4. tmpfs 与命名 volume 精确匹配写路径 allowlist。

首次结果：`4 failed, 1 passed`。失败分别是 user 为 `None`、`read_only` 为 `None`、resource
field 为 `None`、`tmpfs` 为空，准确复现原缺口。

最小 GREEN 修改 `deploy/compose.yaml` 与 `.env.example` 后结果：`5 passed`。

### 6.2 运行时 inspect 合同

先新增 `tests/unit/scripts/test_verify_compose_hardening.py`，覆盖：

- 完整 HostConfig 接受；
- 一个 bad inspect 同时报告八类缺口；
- `10001:0` 这种非 root user + root group 仍拒绝；
- malformed inspect 缺 Config/HostConfig 时 fail-closed。

首次 RED 在 collection 阶段失败：

```text
ModuleNotFoundError: No module named 'scripts.verify_compose_hardening'
```

新增标准库脚本 `scripts/verify_compose_hardening.py` 后：`4 passed`。

### 6.3 CI 防删除合同

再写测试要求 `compose-smoke` 恰好存在一个 `Verify effective container hardening` step，并检查
脚本与五个常驻服务都在命令内。首次结果：`1 failed, 5 passed`，因为 step 不存在。

向 workflow 加入 step 后，两组聚焦测试合计：`10 passed`。

## 7. 实际修改

| 文件 | 修改 | 原因 |
|---|---|---|
| `deploy/compose.yaml` | 六服务 user/read_only/cap_drop/security_opt/resources；tmpfs；缩小 artifact mount | 建立声明式运行边界 |
| `.env.example` | 九个资源 override 与“需实测调参”说明 | 避免把默认值误当不可变生产参数 |
| `scripts/verify_compose_hardening.py` | fail-closed Docker inspect 校验器 | 证明 Docker 的有效配置，不只证明 YAML 文本 |
| `.github/workflows/ci.yml` | readiness 后运行五服务 inspect 校验 | 用真实容器锁定边界 |
| `tests/unit/test_deployment_config.py` | 六项静态/CI 合同 | 防配置回退 |
| `tests/unit/scripts/test_verify_compose_hardening.py` | 四项纯函数合同 | 防校验器本身误接受不安全配置 |

没有修改 `Dockerfile`：它已经使用 UID/GID 10001。Compose 显式 user 是对镜像默认值的运行时
固定，不需要复制或重写现有用户创建逻辑。

## 8. 实施中遇到的问题

### 8.1 Ruff 要求机械格式化

首次 targeted static check 报 3 个新 Python 文件需 formatter。运行项目 Ruff formatter 后，
targeted Ruff 与新脚本 mypy 全部通过。没有手工争辩或放宽格式规则。

### 8.2 额外 mypy 范围暴露 PyYAML stub 缺失

我曾把 unit test 文件也交给 mypy，得到：

```text
Library stubs not installed for "yaml"
```

仓库正式 strict mypy 合同是 `app scripts tests/integration tests/concurrency`，unit tests 从未在该
范围内；CI 也没有安装 `types-PyYAML`。本项没有为一个超出既定范围的额外命令添加依赖，也没有
降低正式规则。最终按 CI 精确范围运行，117 source files 全通过；unit tests 仍由 pytest 和 Ruff
覆盖。

### 8.3 首轮 Gate 聚焦命令被外层超时终止

包含 experiment prepare 的 60 项聚焦命令首次使用 180 秒工具上限，最终 exit 124，约 184 秒
被外层终止，没有 pytest assertion failure。保持相同测试集合并把外层上限提高后：

```text
60 passed in 219.95s
```

最慢四项分别约 62.59、59.67、30.49、29.00 秒，合计已经超过原外层上限。没有删除慢测试、
减少 arm 数或用 sleep“修复”。

### 8.4 本机无 Docker

`Get-Command docker` 返回 `DOCKER_CLI=NOT_FOUND`。因此本机不能声称 official entrypoint、
fresh-volume ownership、read-only/tmpfs 或实际 HostConfig 已验证。该证据由远端 Run #21 提供。

## 9. 验证结果

### 9.1 本地

| 检查 | 结果 | 状态 |
|---|---|---|
| Compose + inspect 聚焦 | 10 passed | `VERIFIED` |
| Gate prepared/preflight/experiment 相关回归 | 60 passed | `VERIFIED` |
| 非 integration 全量 | 455 passed，8 deselected | `VERIFIED` |
| Ruff format | 249 files already formatted | `VERIFIED` |
| Ruff lint | All checks passed | `VERIFIED` |
| strict mypy | 117 source files | `VERIFIED` |
| uv lock | 70 packages resolved | `VERIFIED` |
| 本机 Docker | CLI 不存在 | `NOT_RUN_LOCAL` |

### 9.2 远端

绑定实现提交 `6c84cd92257e5cbe7c4722e37c1acdfe7a9fa5fa` 的
[GitHub Actions Run #21](https://github.com/godofxuan/ai-evalops-platform/actions/runs/30733050517)
最终为 `completed / success`，`quality-and-integration` 与 `compose-smoke` 都成功。

Compose step 级结果：

| step | 结果 |
|---|---|
| Build the complete current topology | success |
| Start and wait for PostgreSQL and Redis | success |
| Apply migrations in the Compose topology | success |
| Start API, Worker, and Reaper | success |
| Verify readiness through the published API port | success |
| Verify effective container hardening | success |
| Stop Compose topology | success |

这证明当前固定的 PostgreSQL 18.4 Alpine、Redis 8.8.1 Alpine 与应用镜像在 fresh named volume 下
能以所声明的非 root/read-only/minimal-capability/resource-limit 合同启动，并且 Docker inspect
看到的有效 HostConfig 符合预期。

质量 job 还实际执行并成功：非 integration、真实 PostgreSQL/Redis integration、P2 migration
downgrade/re-upgrade 与 application image build。

## 10. 本次证明了什么

- 六个 Compose service 都有明确的非 root 运行身份；
- 镜像根文件系统为只读，业务写入仅通过声明的 volume/tmpfs；
- capability 全部丢弃且禁止获取新 privilege；
- 六个服务都有正数 CPU、memory、PID 上限；
- runtime verifier 对缺项和 malformed inspect fail-closed；
- 当前 pinned image、fresh named volume、migration 和应用启动兼容；
- Compose 修改会被 Gate prepared evidence hash 机制识别。

## 11. 仍未证明什么

- 默认资源值没有经过正式 500-case、32-arm、soak 或生产峰值验证；可能需要上调或下调；
- 没有证明 OOM 时的业务恢复、CPU throttling 尾延迟或 PID 达限行为；
- 没有配置自定义 seccomp/AppArmor、rootless Docker 或 user namespace；
- 没有网络分段、强制 egress policy、secret manager 或宿主机/daemon 安全证明；
- read-only root FS 不保护可写的数据库和 artifact volume，数据访问仍依赖应用和数据库权限；
- 当前证据只绑定当前 pinned image；升级 PostgreSQL/Redis/Compose 后必须重跑 fresh-volume smoke；
- 将 named volume 换成 host bind mount 时，宿主目录 ownership 可能需要操作员预先配置；
- 普通 CI success 不等于生产安全审计、容量认证或正式 Gate 通过。

## 12. Migration、schema 与旧 prepared evidence

- 数据库 migration：无；
- API/result/Gate schema version：无变化；
- 历史 `docs/results/`：未修改；
- 正式 evidence：未覆盖；
- prepared bundle：失效。

prepared bundle 失效不是安全功能的副作用，而是 P1-1 的预期行为：本项同时改变 source commit、
`deploy/compose.yaml` hash、CI 和 build context。任何绑定旧 SHA/Compose hash 的 prepared manifest
都必须拒绝执行，并在正式 Gate 前重新 prepare。

## 13. 回滚

代码层回滚：

```text
git revert 6c84cd92257e5cbe7c4722e37c1acdfe7a9fa5fa
```

运行中的旧容器不会因 Git revert 自动改变 HostConfig。回滚或重新加固后都必须 recreate 服务，
例如重新执行 `docker compose up --detach --build --force-recreate`。不需要、也不应为了回滚删除
`postgres_data`、`redis_data` 或 `artifact_data` volume；本项没有数据迁移。

回滚会恢复 root FS 可写、默认 capability、数据库 root entrypoint 和无限资源，因此只能在明确
接受安全退化、或新限制导致无法恢复的兼容故障时执行。

## 14. 简历与面试表述

可用表述：

> 我没有把 Dockerfile 的 `USER` 当成整套拓扑已经非 root。先用测试冻结六个服务的 user、
> read-only、drop ALL、no-new-privileges、资源上限和写路径 allowlist，再用 Docker inspect 在 CI
> 验证有效 HostConfig。数据库显式用官方用户，socket/temp 用 tmpfs，fresh-volume smoke 证明当前
> pinned images 可初始化。默认限额只是开发/CI containment，正式容量 Gate 尚未执行。

不能表述为：

- “容器绝对安全”；
- “生产资源已经调优”；
- “rootless/零权限”；
- “正式 Gate 已通过”；
- “数据库 volume 也只读”。
