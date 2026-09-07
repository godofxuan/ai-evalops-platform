# 发布收口演示（Windows PowerShell 主教程）

这是可执行说明，不是执行成功回执。最终实测范围见 [CLOSEOUT_RESULTS](CLOSEOUT_RESULTS.md) 和交付包 FINAL_RECEIPT.json。只有 local fixture 不需要服务；本机没有合法已注册目标时 durable 教程状态为 **NEEDS_REGISTERED_TARGET**。不通过放宽 SSRF 伪造全新用户验收。

## 0. 固定代码、客户端和私有输出位置

推荐解压完整交付 ZIP 到一个新的受控目录，在解压根目录启动 PowerShell。不要在原项目未提交工作区切换版本。以下脚本从包内真实回执取 CODE；源码快照不含 .git，运行依赖必须按锁安装：

~~~powershell
$ErrorActionPreference = 'Stop'
$bundleRoot = (Get-Location).Path
$receipt = Get-Content "$bundleRoot/FINAL_RECEIPT.json" -Raw | ConvertFrom-Json
$codeSha = $receipt.new_code_sha
if ($codeSha -notmatch '^[0-9a-f]{40}$') { throw '缺少真实 NEW_CODE_SHA' }
Set-Location "$bundleRoot/source_current"
uv python install 3.12
if ($LASTEXITCODE -ne 0) { throw 'Python 安装失败' }
uv sync --locked --all-groups
if ($LASTEXITCODE -ne 0) { throw '锁定环境同步失败' }
$python = (Resolve-Path '.venv/Scripts/python.exe').Path
$demoRoot = Join-Path $bundleRoot ('private-demo-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $demoRoot | Out-Null
~~~

若从 Git 使用，请在单独 clone 中检出回执的 CODE，不以最新 main、DOC 或随意填入的 40 字符替代执行身份。本轮发布候选已各跑一次，包中有原始运行结果；下面是你自己的后续学习演示，不属于再次挑选发布成绩。

## 1. 无服务的确定性演示

~~~powershell
& $python -m scripts.run_product_experiment --spec benchmarks/product_demo_v1/experiment.json --output-dir "$demoRoot/qa-local" --export-mode private --evalops-sha $codeSha
$qaExit = $LASTEXITCODE
& $python -m scripts.run_product_experiment --spec benchmarks/agent_tool_demo_v1/experiment.json --output-dir "$demoRoot/agent-local" --export-mode private --evalops-sha $codeSha
$agentExit = $LASTEXITCODE
& $python -m scripts.verify_product_experiment "$demoRoot/qa-local/manifest.json"
& $python -m scripts.verify_product_experiment "$demoRoot/agent-local/manifest.json"
~~~

两套各 120 题，均为 SYNTHETIC_FIXTURE，不调用真实模型。质量门禁退出码：0 自动演示通过、1 质量失败、2 输入/证据不足、3 执行失败。保存实际输出，非零不能直接重跑追绿。local 验证输出 **LOCAL_PRIVATE_STRUCTURE_ONLY** 和 reported_quality_status，quality_recomputed=false；不能声称原始观测语义已重算。

## 2. 显式启用隔离开发实例（本轮不自动部署）

已有合法测试实例可直接用其地址/key，跳过启动。只有确认是自己新建的测试实例、端口未占用后，才执行下面命令。Compose 依赖、映射端口和资源需由操作者核实，端口冲突时停止，不杀已有服务。

管理员须先通过现有 EVALOPS_HTTP_TARGET_REGISTRY 配置两组合法 HTTP 目标。注册配置中的版本必须与目标说明一致；客户端不接收目标 URL/令牌。没有注册目标时停在 NEEDS_REGISTERED_TARGET，不使用测试 DNS/peer 替换器。

~~~powershell
if (-not $env:EVALOPS_HTTP_TARGET_REGISTRY) { throw 'NEEDS_REGISTERED_TARGET：缺少管理员测试目标注册配置' }
$project = 'evalops-resume-' + (Get-Date -Format 'yyyyMMddHHmmss')
$env:EVALOPS_PRODUCT_EXECUTION_CODE_SHA = $codeSha
docker compose -p $project -f deploy/compose.yaml -f deploy/compose.product-experiments.yaml up --build --wait
if ($LASTEXITCODE -ne 0) { throw '隔离实例启动失败；保留诊断，不继续' }
$env:EVALOPS_API_URL = 'http://127.0.0.1:8000'
~~~

默认 compose 提交开关仍关闭，覆盖文件只显式启用 API；CODE 由操作者声明，不是运行时远程认证。不要改生产配置。需要清理时仅针对保存的 $project；不运行全局 prune，也不删除别人的卷。

## 3. 获取开发 key，不进入公开记录

已有测试 key 放在当前进程 EVALOPS_API_KEY 即可，不打印它，不用 PowerShell Transcript。只有自己创建的开发实例才运行以下创建操作；stdout 在变量中接收，不写入公开文件：

~~~powershell
if (-not $env:EVALOPS_API_KEY) {
  $keyLines = docker compose -p $project -f deploy/compose.yaml -f deploy/compose.product-experiments.yaml exec -T api python -m scripts.create_dev_api_key --tenant-slug resume-demo --expires-in-days 1
  if ($LASTEXITCODE -ne 0) { throw '开发 key 创建失败' }
  $keyLine = $keyLines | Where-Object { $_ -like 'API key (shown once): *' } | Select-Object -First 1
  if (-not $keyLine) { throw '没有取得一次性 key；不要反复创建' }
  $env:EVALOPS_API_KEY = $keyLine.Substring('API key (shown once): '.Length)
  $keyLine = $null; $keyLines = $null
}
~~~

key 仅在客户端进程环境中；终端关闭后需从自己的受控凭据存储恢复，不能从服务端反查明文。不要运行打印整个环境的命令。

## 4. 映射、创建数据集、捕获版本并构造 request

管理员提供受控的目标说明 JSON 文件，以 EVALOPS_DEMO_TARGETS_FILE 指向它。顶层仅 baseline/candidate；每组仅 target_id、target_version、source_repository、source_sha，均来自真实注册配置/版本记录。它不含 API key 或目标凭据。目标 source_sha 为客户端声明，服务端不把它当作已认证源码。

~~~powershell
if (-not $env:EVALOPS_API_URL -or -not $env:EVALOPS_API_KEY -or -not $env:EVALOPS_DEMO_TARGETS_FILE) {
  throw 'NEEDS_REGISTERED_TARGET：需要实际 API、租户 key 和注册目标说明文件'
}
$prepared = Join-Path $demoRoot 'durable-qa'
& $python -m scripts.prepare_product_client_demo --spec benchmarks/product_demo_v1/experiment.json --api-url $env:EVALOPS_API_URL --targets $env:EVALOPS_DEMO_TARGETS_FILE --output-dir $prepared
if ($LASTEXITCODE -ne 0) { throw '准备未完成；检查现有 receipt，不能换目录盲目重试创建' }
$mapping = Get-Content "$prepared/mapping.json" -Raw | ConvertFrom-Json
$version = Get-Content "$prepared/dataset-version.json" -Raw | ConvertFrom-Json
$request = Get-Content "$prepared/request.json" -Raw | ConvertFrom-Json
if ($request.dataset_version_id -ne $version.id) { throw '真实版本 ID 不匹配' }
if ($mapping.normalized_dataset_sha256 -ne $version.sha256) { throw '规范化摘要不匹配' }
~~~

助手使用 map_product_dataset，先校验原始 cases.json 摘要，再生成 normalized.jsonl。source_dataset_sha256 绑定原始 JSON；上传版本的 sha256 绑定规范化 JSONL，两者不可互换。dataset.json、dataset-version.json 捕获 API 的实际 UUID；request.json 使用真实 version.id。若上传前断网，可能只留下 dataset.json；创建不具备自动重试保证，先核实已有 ID。所有输出是 PRIVATE_CONTROLLED_INPUT，不能直接公开。

Agent 等价入口使用 benchmarks/agent_tool_demo_v1/experiment.json、另一个新输出目录及适合 Agent 的已注册目标说明；不改 policy、gold 或预算追求通过。

## 5. 提交、短超时、退出客户端与同 ID 恢复

~~~powershell
$idem = 'resume-qa-' + (Get-Date -Format 'yyyyMMddHHmmss')
$idem | Set-Content "$prepared/idempotency-key.txt"
$acceptedText = & $python -m scripts.product_experiment_client --api-url $env:EVALOPS_API_URL submit --request "$prepared/request.json" --dataset "$prepared/cases.json" --idempotency-key $idem
if ($LASTEXITCODE -ne 0) { throw '提交结果不确定，保留同键同文件进行重放' }
$acceptedText | Set-Content "$prepared/accepted.json" -Encoding utf8
$accepted = $acceptedText | ConvertFrom-Json
$experimentId = $accepted.id
& $python -m scripts.product_experiment_client --api-url $env:EVALOPS_API_URL wait $experimentId --wait-seconds 1 --poll-seconds 2
$waitExit = $LASTEXITCODE
if ($waitExit -notin 0,4) { throw '等待发生实际错误' }
~~~

每条 python 都是独立客户端进程；wait 返回 4 是本地超时，不取消实验。它也可能已经取得终态而返回 0，不能为了“展示超时”篡改服务器。可关掉终端，在新终端恢复固定源码目录、$python、$prepared、API 地址与受控 key，然后从文件恢复，不手抄 UUID：

~~~powershell
$accepted = Get-Content "$prepared/accepted.json" -Raw | ConvertFrom-Json
$experimentId = $accepted.id
$idem = (Get-Content "$prepared/idempotency-key.txt" -Raw).Trim()
& $python -m scripts.product_experiment_client --api-url $env:EVALOPS_API_URL get $experimentId
$replayText = & $python -m scripts.product_experiment_client --api-url $env:EVALOPS_API_URL submit --request "$prepared/request.json" --dataset "$prepared/cases.json" --idempotency-key $idem
if ($LASTEXITCODE -ne 0) { throw '同键重放失败' }
$replay = $replayText | ConvertFrom-Json
if ($replay.id -ne $accepted.id -or $replay.baseline_run_id -ne $accepted.baseline_run_id -or $replay.candidate_run_id -ne $accepted.candidate_run_id) { throw '重放没有返回原实验/Run' }
& $python -m scripts.product_experiment_client --api-url $env:EVALOPS_API_URL wait $experimentId --wait-seconds 300 --poll-seconds 2
~~~

同键不同参数应 409；不可换键新建后冒充恢复。READY_FOR_ASSESSMENT 是可评估状态，不是质量 PASS。cancel 需要显式命令，会影响尚未完成任务，不保证撤销目标已有副作用。

## 6. 导出与离线复算

~~~powershell
& $python -m scripts.product_experiment_client --api-url $env:EVALOPS_API_URL export $experimentId --output-dir "$prepared/public"
$publicExit = $LASTEXITCODE
& $python -m scripts.product_experiment_client --api-url $env:EVALOPS_API_URL export $experimentId --include-private --dataset "$prepared/cases.json" --output-dir "$prepared/private"
$privateExit = $LASTEXITCODE
# 以下不连接服务器；目录包含服务器精确报告字节和原始输入。
& $python -m scripts.product_experiment_client verify "$prepared/private"
& $python -m scripts.product_experiment_client verify "$prepared/public"
~~~

导出非零可能是报告质量失败但文件完整生成，应查看实际 quality_status，而不是重跑实验。私有完整包通过才标 PRIVATE_RECOMPUTED；公有包为 PUBLIC_PROJECTION_ONLY。单报告库缺原始输入为 PRIVATE_SOURCE_REQUIRED，完整私有包不接受缺输入。若有独立可信的原报告 SHA，可加 --expected-report-sha256；包内自己宣称的 hash 不是来源认证。

## 7. 失败与 Worker 恢复展示（不接真实模型）

本地：python -m pytest -q tests/unit/product_experiments/test_observation_contract.py，观察超长答案执行失败报告、终态冲突拒绝、合法边界保留。它使用临时合成输入，目标 DNS/peer 仅测试注入，普通入口策略未修改。

真实数据库证据入口：tests/integration/test_product_experiment_persistence.py。它实际构造应用、鉴权、创建版本、持久两组任务，调用现有 worker/claimer/heartbeat/reaper/committer 和真实本地 TCP；没有用内存仓库替代 PostgreSQL。tests/product_process_recovery.py 杀死自己生成的 OS 子进程，等待真实租约到期后接管，拒绝旧 claim 迟到提交；“HTTP 成功但提交前死亡”允许外部重复调用。API 的测试传输为 ASGI，目标公网 DNS/peer 为测试替代，**不是生产公网 TLS 验收**。客户端退出和 Worker 死亡不是同一件事。最终 CI 的具体 executed/skipped 状态见回执，不能只引用这段说明。

## Bash 等价入口

同样在交付包根目录，先读取 FINAL_RECEIPT 再进入 source_current；环境变量由实际测试实例提供：

~~~bash
CODE_SHA=$(python3 -c 'import json; print(json.load(open("FINAL_RECEIPT.json"))["new_code_sha"])')
cd source_current
uv python install 3.12 && uv sync --locked --all-groups
export EVALOPS_PRODUCT_EXECUTION_CODE_SHA="$CODE_SHA"
uv run --no-sync python -m scripts.prepare_product_client_demo --spec benchmarks/product_demo_v1/experiment.json --api-url "$EVALOPS_API_URL" --targets "$EVALOPS_DEMO_TARGETS_FILE" --output-dir ../private-durable-qa
# 后续相同 CLI；JSON 中 id 用 python 的 json.load 读取，不填写假 UUID。
~~~

不要把私有目录、key、环境转储或数据库转储加入 Git。该教程不授权生产部署，不建立正式 A/B、人评或扩容验收。
