# 官方评测、Trace 与前端可视化 Runbook

> **2026-08-30 更新：** 单进程与并行 Trace 评测现在自动生成统一 `trace.json`；前端点击“选择 Trace JSON”即可本地读取。默认流水线不再重跑排序代码，而是直接导出日志。完整约定与旧结果补导出方法见 [Trace JSON 格式](TRACE_JSON_FORMAT.md)。下文的精确重放工具仅保留为可选历史入口。

> 目标：让团队成员或其 Agent 从一个干净工作区出发，能够一致地完成代码测试、官方规则评测、逐节点 Trace 保存、目标商品流失诊断和前端展示。

## 1. 先说结论：应该使用哪个入口

仓库里有三类入口，职责不同：

| 目的 | 推荐入口 | 是否调用 DeepSeek | 是否保存完整 Trace |
|---|---|---:|---:|
| 跑 Python 测试 | `pytest tests` | 否 | 否 |
| 验证官方基础评分器 | `python -m evaluator.local_evaluator` | 取决于环境开关 | 否 |
| 团队正式全量评测 | `scripts/evaluate_parallel_with_traces.py` | 是 | 是 |
| 一键完成测试、评测和前端刷新 | `scripts/run_test_trace_frontend.ps1` | 是 | 是 |

团队日常对比模型、召回或排序改动时，优先使用仓库根目录的一键入口：

```powershell
cd C:\path\to\tiktok_project_4
.\scripts\run_test_trace_frontend.ps1
```

它会依次完成：

1. 运行 `techjam-conversational-search/tests` 下的全部测试。
2. 使用官方 evaluator 的用户模拟、命中判定和评分公式运行 200 条公开集。
3. 开启 DeepSeek，保证 Agent 的意图理解和对话决策走当前 LLM 架构。
4. 按 worker 分片并行执行，聚合为一份结果。
5. 保存每个 session、每轮对话和每个 LangGraph 节点的 Trace。
6. 从保存的节点日志导出统一 `trace.json`；快照不足时明确标记排名未知。
7. 将该文件复制为前端默认 `diagnostics.json` 并执行前端生产构建，也可直接在页面选择任意运行的 `trace.json`。

这里使用 LLM 的是被测 Agent，不是另一个 LLM 裁判。最终分数仍由官方确定性公式计算。

## 2. 目录约定

本文假设工作区结构如下：

```text
tiktok_project_4/
├─ scripts/
│  └─ run_test_trace_frontend.ps1       一键流水线
├─ docs/
│  └─ TEST_TRACE_VISUALIZATION_RUNBOOK.md
├─ techjam-conversational-search/       Agent、官方 evaluator 和评测产物
│  ├─ evaluator/local_evaluator.py
│  ├─ scripts/evaluate_with_traces.py
│  ├─ scripts/evaluate_parallel_with_traces.py
│  ├─ evaluation_runs/
│  └─ .env
└─ trace-visualizer/                    Trace 可视化前端
   ├─ scripts/build-diagnostics.py
   ├─ public/diagnostics.json
   └─ app/page.tsx
```

如果目录被移动，可以直接调用底层脚本并显式传入 `--project-root`、`--evaluation-root`、`--run-dir` 和 `--output`。

## 3. 首次环境准备

### 3.1 Python 环境

```powershell
cd techjam-conversational-search
uv sync --extra deepseek --group dev
```

项目要求 Python 3.12。脚本优先使用：

```text
techjam-conversational-search/.venv/Scripts/python.exe
```

如果该解释器不存在，一键脚本会尝试使用 `uv run python`。

### 3.2 DeepSeek 配置

在 `techjam-conversational-search/.env` 中配置：

```dotenv
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
SHOPPING_AGENT_ENABLE_LLM=true
```

要求：

- 不要把 `.env`、API Key 或访问令牌提交到 Git。
- `evaluate_parallel_with_traces.py` 会显式设置 `SHOPPING_AGENT_ENABLE_LLM=true`。
- 每个 LLM 请求温度为 0；供应商仍可能存在少量服务端非确定性。
- 429、连接错误和 5xx 会重试一次；业务层仍保留本地 fallback。

### 3.3 前端环境

```powershell
cd ..\trace-visualizer
npm install
```

Node.js 要求 22.13 或更高版本。

## 4. 推荐流程：一条命令执行

### 4.1 全量正式跑法

```powershell
cd C:\path\to\tiktok_project_4
.\scripts\run_test_trace_frontend.ps1
```

默认参数：

- 数据集：`data/public_set.jsonl`，共 200 条。
- 模型：`deepseek-v4-pro`。
- worker：当前机器逻辑处理器数量。
- 每节点默认保存全部候选商品及其顺序、分数（仅影响日志，不改变召回或排序）；`CandidateLimit=0` 表示不限量。
- 评测根目录：`evaluation_runs/parallel_pro_200`。

### 4.2 显式指定并发和模型

```powershell
.\scripts\run_test_trace_frontend.ps1 `
  -Workers 12 `
  -Model deepseek-v4-pro `
  -CandidateLimit 0
```

并发原则：

- 不同样本彼此隔离，分片不会改变官方计分公式。
- 每个 worker 都会加载目录、索引和精排器，因此 worker 越多，内存占用越高。
- 推荐以逻辑 CPU 数为上限；不要只根据 API 并发能力无限增加进程。
- 如果大量出现 429 或机器内存压力明显，应降低 `-Workers`，而不是修改评测逻辑。

### 4.3 复用已有评测，只刷新前端

BGE cross-encoder 实验已于 2026-08-30 撤下；一键脚本不再接受 `-Reranker` 参数。
正式链路直接使用 `PreciseReranker`，评测配置记录 `mode=precise`。
历史 BGE 日志和快照仍可查看，但不能用当前排序器重放为旧实验结果。
独立的 BGE 向量召回功能不受此次撤回影响。

```powershell
.\scripts\run_test_trace_frontend.ps1 `
  -SkipTests `
  -SkipEvaluation
```

该命令读取：

```text
techjam-conversational-search/evaluation_runs/parallel_pro_200/LATEST.txt
```

然后重新生成 `trace-visualizer/public/diagnostics.json` 并构建前端，不调用 DeepSeek。

### 4.4 只评测、不重新构建前端

```powershell
.\scripts\run_test_trace_frontend.ps1 -SkipFrontendBuild
```

诊断 JSON 仍会更新，只跳过 `npm run build`。

## 5. 手动分步执行

当需要定位某个阶段的问题时，可以不用一键脚本。

### 5.1 跑全部测试

在仓库根目录执行（不会启动正式评测、诊断重放或前端构建）：

```powershell
.\scripts\run_test_trace_frontend.ps1 -TestsOnly
```

或手动指定每次独立的临时目录，并禁用 pytest 缓存：

```powershell
cd techjam-conversational-search
$pytestTemp = Join-Path $PWD (".pytest-run-" + [Guid]::NewGuid().ToString("N"))
.\.venv\Scripts\python.exe -m pytest tests -q `
  "--basetemp=$pytestTemp" -p no:cacheprovider
```

测试目录：

- `tests/unit`：纯函数、接口和包边界。
- `tests/integration`：Agent 与 evaluator 集成。
- `tests/regression`：会话状态、推荐行为和节点 Trace 回归。

脚本为每次测试生成独立的项目内临时目录，且不使用 `.pytest_cache`，避免复用其他 Windows 账户创建的受限目录。不要将新目录放在旧的 `.pytest_tmp` 父目录下。

### 5.2 跑官方基础 evaluator

```powershell
.\.venv\Scripts\python.exe -m evaluator.local_evaluator `
  --output results.json
```

这是最接近官方基础入口的单进程版本。它输出分数与 session 结果，但不保存逐轮、逐节点 Trace。

### 5.3 跑带 Trace 的单进程版本

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_with_traces.py `
  --llm `
  --candidate-limit 0
```

该入口适合调试单个分片或少量样本。正式全量测试使用并行入口。

### 5.4 跑带 Trace 的并行全量版本

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_parallel_with_traces.py `
  --workers 12 `
  --model deepseek-v4-pro `
  --candidate-limit 0 `
  --output-root evaluation_runs\parallel_pro_200
```

并行脚本所做的事情：

1. 轮询分配 200 条样本到多个 shard。
2. 每个 shard 启动独立 `evaluate_with_traces.py --llm` 进程。
3. 每个进程使用相同官方用户模拟和评分规则。
4. 所有进程成功后，按 `sample_id` 和 `turn` 聚合结果。
5. 使用 `evaluator.local_evaluator.metric_summary` 计算最终指标。

不要把 `scripts/evaluate_with_deepseek.py` 作为本流程的正式入口。团队统一使用上面的并行 Trace 脚本，避免结果产物格式不一致。

## 6. 一次评测会生成什么

### 中断后只查看已保存的 Trace（不重跑模型）

在仓库根目录执行：

```powershell
$runDir = (Get-Content techjam-conversational-search/evaluation_runs/bge_pro_200/LATEST.txt -Raw).Trim()
.\techjam-conversational-search\.venv\Scripts\python.exe trace-visualizer/scripts/build-trace-preview.py `
  --run-dir "$runDir" --output trace-visualizer/public/diagnostics-bge-preview.json
npm --prefix trace-visualizer run dev
```

打开终端 Local 地址并加上 `?data=diagnostics-bge-preview.json`，可再加 `&sample=public_0068` 定位样本。原来的 `diagnostics.json` 和精确重放入口保持不变。

该入口只读取分片日志，展示已完成样本；未完成样本仍保留在原始日志中，不计入指标。页面明确标记部分结果，并将已保存快照之外的目标排名显示为未知，不误判为未召回。它不调用 BGE、DeepSeek，也不生成或替代正式评测汇总。

聚合运行目录示例：

```text
evaluation_runs/parallel_pro_200/20260829_232205_+0800/
├─ run_config.json
├─ summary.json
├─ report.md
├─ sessions.jsonl
├─ turns.jsonl
├─ node_traces.jsonl
└─ shards/
```

### `run_config.json`

记录本次运行的模型、worker 数、目录、数据集、样本数和 Trace 候选上限。用于确认两个实验是否可比。

### `summary.json`

机器可读的总分，包括：

- `hit_rate_at_10`
- `mrr`
- `mttc`
- `efficiency`
- `recommended_technical_score`
- token 使用量
- 各场景拆分指标
- 各 shard 的原始路径与分数

### `report.md`

给人看的精简评测报告。对外同步结果时优先使用它，深入分析时读取 JSONL。

### `sessions.jsonl`

每行一个完整评测样本，包含：

- `sample_id` 与场景类型
- 标准答案 `target_parent_asin`
- 目标商品完整信息
- 是否命中、首次命中轮次和最佳排名
- 实际披露的约束
- 本 session 错误列表

### `turns.jsonl`

每行一个对话轮次，包含：

- 用户消息与 Agent 响应
- 推荐的 `parent_asin` 列表
- 标准答案在最终推荐中的排名
- intent override 是否已经生效
- 当前结构化意图和 `semantic_query`
- 各候选集合数量
- 延迟、token 和错误

### `node_traces.jsonl`

每行是某个轮次中的一个 LangGraph stage，包含：

- `sample_id`、`turn`、`stage_index`
- 本 stage 执行了哪些节点
- 节点写入 `ShoppingState` 的字段
- 候选列表的数量与前 N 条快照

注意：文件扩展名是 `.jsonl`，不是普通 JSON 数组。必须逐行解析。

### `shards/`

保存每个 worker 的数据切片、stdout、stderr 和原始运行目录。聚合失败时先检查：

```text
shards/shard_XX/stderr.log
```

## 7. 为什么前端不能直接只读 `node_traces.jsonl`

`node_traces.jsonl` 现在默认保存每个候选节点的完整列表（`--candidate-limit 0`），不限于前 20、200 或 500 条。后续评测按此约定执行，不为缩小日志自动截断候选。并行聚合逐行复制完整节点日志，导出器逐行提取目标证据；原始日志较大，前端 `trace.json` 仍只保存展示所需的排名和分数。

旧运行或显式使用正数上限的调试运行，仍保留原快照边界，不能自动补齐。对于这些截断快照，未发现目标可能有两种含义：

1. 这个节点完全没有召回目标。
2. 目标存在，但排名在该次运行设置的快照上限之外。

仅靠截断快照未必能判断标准答案究竟在哪一步被丢弃；每个节点的 `count` 仍记录真实候选总数。

现在默认直接导出 `trace.json`，保留“排名未知”的真实边界，不重放模型。下图是仍可手动使用的**旧精确重放入口**，不再是默认流水线：

```text
sessions.jsonl
turns.jsonl
node_traces.jsonl
        │
        ▼
scripts/build-diagnostics.py
        │
        ├─ 读取已保存的 LLM 结构化意图
        ├─ 复用当前 CatalogIndex / LocalDenseIndex / AttributeIndex
        ├─ 复用 RRF、硬过滤和 PreciseReranker
        ├─ 对标准答案计算每个阶段的完整精确排名
        └─ 不再调用 LLM
        ▼
public/diagnostics.json
        │
        ▼
Trace 前端
```

离线重放只重算确定性的召回和排序阶段。用户消息、LLM 解析结果、intent override 门控和最终推荐仍来自原始评测产物。

## 8. 生成前端数据

推荐直接选择运行目录中自动生成的 `trace.json`。旧运行用 `scripts/export_trace.py --run-dir <目录>` 补导出。下面的 8.1 等小节仅用于旧精确重放，要求代码版本与原始评测一致；不适合直接混用 main 和 yxh_3。

### 8.1 使用最新一次运行

```powershell
cd trace-visualizer
..\techjam-conversational-search\.venv\Scripts\python.exe `
  scripts\build-diagnostics.py
```

脚本默认读取：

```text
../techjam-conversational-search/evaluation_runs/parallel_pro_200/LATEST.txt
```

并写入：

```text
public/diagnostics.json
```

### 8.2 使用指定运行，保证实验可复现

```powershell
..\techjam-conversational-search\.venv\Scripts\python.exe `
  scripts\build-diagnostics.py `
  --run-dir "C:\path\to\evaluation_runs\parallel_pro_200\RUN_ID"
```

可用参数：

```text
--project-root     Agent 项目目录
--evaluation-root  评测根目录，省略 run-dir 时读取其 LATEST.txt
--run-dir           指定一次聚合运行目录
--output            diagnostics.json 输出位置
```

生成完成后应检查控制台最后一行包含输出文件路径和字节数。

## 9. 打开最新前端

```powershell
cd trace-visualizer
npm run dev
```

打开终端打印的 Local URL，通常是：

```text
http://localhost:3000/
```

生产构建校验：

```powershell
npm run build
```

前端支持：

- 按命中状态、场景和流失阶段筛选 200 个样本。
- 搜索 `sample_id`、目标 `parent_asin` 或商品名。
- 切换对话轮次。
- 查看词法、语义、属性三路并行召回。
- 查看 RRF、硬约束过滤、精排和最终 Top 10。
- 点击节点查看标准答案的排名、分数和候选总数。
- 区分真正丢失与 intent override 尚未生效时的评测门控。

前端页头的 Run ID、模型、worker 数和总分必须与所选运行的 `summary.json` 一致。否则说明 `diagnostics.json` 没有刷新。

## 10. 流失阶段如何定义

| 诊断 | 判定 |
|---|---|
| `recall` | 词法、语义、属性三路均没有目标商品 |
| `fusion` | 至少一路召回目标，但目标未进入 RRF Top 500 |
| `filter` | 目标进入融合结果，但被硬约束过滤 |
| `rerank` | 目标通过过滤，但精排后位于第 11 名以后 |
| `response` | 目标进入精排 Top 10，但最终响应中不存在 |
| `gated` | 目标已推荐，但 intent override 尚未生效，官方评测暂不计命中 |
| `hit` | 评测门控已开启，目标进入最终推荐 Top 10 |

诊断时优先关注未命中 session 的有效评测轮次。`gated` 不是模型错误，不能计为召回或排序流失。

## 11. 结果验收清单

Agent 执行完流程后必须检查以下项目：

- [ ] `pytest` 全部通过，没有把权限错误误报成代码失败。
- [ ] 所有 shard 退出码为 0。
- [ ] 聚合 `sample_count` 等于数据集样本数，公开集应为 200。
- [ ] `sessions.jsonl` 的唯一 `sample_id` 数等于 200。
- [ ] `turns.jsonl` 不存在非空 `error`。
- [ ] `sessions.jsonl` 不存在非空 `errors`。
- [ ] 每个 LLM 轮次有合理的 token 使用量。
- [ ] `summary.json`、`report.md` 和聚合 JSONL 均存在。
- [ ] `diagnostics.json` 的 Run ID 与 `summary.json` 相同。
- [ ] `npm run build` 成功。
- [ ] Git 中只出现预期的代码、文档和新评测产物。

可用下面的只读检查快速验证聚合完整性：

```powershell
$run = (Get-Content evaluation_runs\parallel_pro_200\LATEST.txt).Trim()
$sessions = Get-Content "$run\sessions.jsonl"
$turns = Get-Content "$run\turns.jsonl"
"sessions=$($sessions.Count) turns=$($turns.Count)"
```

## 12. 常见问题

### pytest 报 Temp / `.pytest_tmp` / `.pytest_cache` 无权限

这不是业务代码或 cross-encoder 失败。旧目录可能由沙箱账户创建，当前用户没有访问权限。更新后的一键脚本使用全新的 `.pytest-run-<随机 ID>` 目录并禁用 pytest 缓存，无需删除旧目录、修改权限或重装环境。

可以先只验证本地测试：

```powershell
.\scripts\run_test_trace_frontend.ps1 -TestsOnly
```

### 并行评测某个 shard 失败

查看对应 `stderr.log`。不要直接聚合部分成功的 shard，因为这会改变样本数和最终得分。

### API 出现 429

降低 worker 数重新完整运行。不要只重跑失败的单个 turn 后手工拼接结果。

### 前端显示旧结果

重新运行：

```powershell
.\scripts\run_test_trace_frontend.ps1 -SkipTests -SkipEvaluation
```

然后刷新浏览器，核对页头 Run ID。

### 修改了召回或精排代码后能否复用旧 Trace

不能用旧分数代表新代码表现。应该重新跑完整评测。

如果只是调整前端展示，可以用 `scripts/export_trace.py --run-dir <运行目录>` 从旧日志生成 `trace.json`，无需调用模型，也不受当前排序代码变化影响。仅当手动使用旧 `build-diagnostics.py` 精确重放工具时，才必须确保当前排序代码与原始运行版本一致。

## 13. 给其他 Agent 的最短执行指令

可以直接把下面这段交给同事的 Agent：

```text
在 tiktok_project_4 根目录执行官方评测与 Trace 前端流水线。
先确认 techjam-conversational-search/.env 已配置 DEEPSEEK_API_KEY，但绝不打印或提交密钥。
运行 .\scripts\run_test_trace_frontend.ps1，默认 worker 使用逻辑 CPU 数。
必须等待全部 pytest、全部 shard、Trace 聚合、diagnostics.json 生成和 npm build 完成。
失败时读取对应 shard 的 stderr.log，不得用部分 shard 计算结果。
完成后汇报 summary.json 中的 HitRate@10、MRR、MTTC、Efficiency、Technical Score、总耗时、worker 数、错误数，以及前端 diagnostics.json 的 Run ID。
不要使用额外 LLM 裁判；DeepSeek 只用于被测 Agent 的意图理解和对话决策。
```
