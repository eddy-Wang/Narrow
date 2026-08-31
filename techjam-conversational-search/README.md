# Shopping Agent

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

[架构](docs/agent_architecture.md) · [组件接口](docs/contracts/component_interfaces.md) · [模型训练](docs/lambdamart_training.md) · [数据格式](data/README.md) · [代码测试](../docs/TESTING.md)
