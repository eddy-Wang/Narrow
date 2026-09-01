# 测试与评测

[English (primary)](TESTING.md) · [中文 README](../README.zh-CN.md) · [数据格式](../techjam-conversational-search/data/README.zh-CN.md)

所有 PowerShell 命令从仓库根目录执行。

## 在线评测

按 README 配置 `.env` 并提供 `data/catalog.jsonl`、`data/test/users.jsonl` 后运行：

```powershell
.\run_evaluation.ps1
```

默认 DeepSeek + LambdaMART，4 个 worker，终端每 5 秒刷新进度。模型名读取 `DEEPSEEK_MODEL`。输出位于后端 `evaluation_runs/test/<时间戳>/`。

需要指定其他数据路径或参数时，直接调用底层脚本：

```powershell
.\run_local_python.ps1 scripts/evaluate_parallel_with_traces.py `
  --catalog 'C:\datasets\catalog.jsonl' `
  --dataset 'C:\datasets\users.jsonl' `
  --ltr-ranker lambdamart --ltr-model-dir models/lambdamart_synthetic_2000 `
  --workers 4 --progress-interval 5 --candidate-limit 0 `
  --output-root evaluation_runs/custom
```

可用 `--model deepseek-v4-pro` 覆盖环境中的模型名。`--candidate-limit 0` 保存完整候选快照，正数仅截断诊断快照，不改变实际召回/排序。`run_local_python.ps1` 将工作目录切换到后端；输入和输出相对路径均按后端目录解析。

并行脚本运行在线评测；单进程调试使用 `scripts/evaluate_with_traces.py`，其 `--llm` / `--no-llm` 控制模型调用。主评测入口不会自动切换到离线模式。

## 代码测试

使用现有 Python 环境；未安装时先执行 README 的安装命令。下列测试使用受控模型响应，不调用真实 API：

```powershell
New-Item -ItemType Directory -Force test_results | Out-Null
$env:SHOPPING_AGENT_ENABLE_LLM = "false"
$env:SHOPPING_DENSE_BACKEND = "local"
$env:LANGSMITH_TRACING = "false"

.\run_local_python.ps1 -m pytest -c pyproject.toml tests ../user-simulator/tests `
  -o "pythonpath=. src ../user-simulator/src" -q -p no:cacheprovider `
  --basetemp .pytest-run-regression --junitxml=../test_results/python.xml

npm --prefix demo-frontend test -- --reporter=default --reporter=junit --outputFile=../test_results/frontend.xml
node --experimental-strip-types --test --test-reporter=tap `
  --test-reporter-destination=test_results/trace.tap `
  trace-visualizer/scripts/tests/trace-format.test.mjs
```

前端依赖安装与启动见[README](../README.md)。代码测试不产生业务命中率。

## 页面评测

工作台的 Native / TechJam 使用 `data/public_set.jsonl`，Realistic 从 catalog 生成需求场景；新运行保存在 `demo_runs/<运行 ID>/`。分别最多 200 / 200 / 100 条，一次运行一个任务。

CLI 的自定义用户测试集不经过网页上传。CLI 结果不会自动登记到网页历史，直接在 Trace 查看器导入输出目录里的 `trace.json`。

## 产物管理

评测目录、工作台运行、原始 LLM 调用和完整候选 Trace 均不提交到 Git。它们可能包含测试内容、本机路径，并且体积可达数百 MB。需要共享证据时，优先提供当前提交生成的 `report.md`、`summary.json` 和经过检查的 `trace.json`；私有测试输入与密钥不得上传。

当前公开开发分、选择规则和局限见 [Flash 对比报告（英文）](../techjam-conversational-search/docs/mrr_loss_search_20260901.md)。该报告不是私有榜单成绩。
