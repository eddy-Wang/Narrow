# Shopping Agent

[English (primary)](README.md)

安装、API 配置、数据位置和运行命令见[根 README](../README.md)。

主评测入口为仓库根目录的 `run_evaluation.ps1`，使用 DeepSeek 完成需求理解和对话决策，使用已训练的 LambdaMART 模型精排。Python 接口由 [submission_agent.py](submission_agent.py) 导出 `Agent`。

## 模块

| 目录 | 职责 |
|---|---|
| `src/shopping_agent/understanding/` | LLM 需求解析和状态更新 |
| `src/shopping_agent/retrieval/` | 动态多路召回、融合和约束过滤 |
| `src/shopping_agent/ranking/` | LambdaMART 精排与特征提取 |
| `src/shopping_agent/dialogue/` | 追问和回复决策 |
| `src/shopping_agent/orchestration/` | LangGraph 执行流程 |
| `src/shopping_agent/application/` | 多轮会话接口 |
| `scripts/` | 评测、Trace 导出和训练工具 |
| `models/lambdamart_synthetic_2000/` | 已训练模型及特征元数据 |

## 文档

| 文档 | 用途 |
|---|---|
| [架构](docs/agent_architecture.md) | 运行图、状态、召回和可靠性边界 |
| [组件接口](docs/contracts/component_interfaces.md) | 理解、召回、排序和对话之间的契约 |
| [LambdaMART 训练](docs/lambdamart_training.md) | 训练数据、特征、隔离与复现 |
| [MRR 训练](docs/mrr_training.md) | 当前目标函数和受限选模流程 |
| [数据格式](data/README.md) | Catalog 和场景 JSONL 格式 |
| [代码测试](../docs/TESTING.md) | 离线检查、在线评测与生成产物 |
