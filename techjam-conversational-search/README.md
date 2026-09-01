# Shopping Agent

[中文备用说明](README.zh-CN.md) · [Root README](../README.md) · [Judge's file guide](../docs/JUDGE_GUIDE.md)

See the root README for installation, API configuration, data placement, and
run commands. `run_evaluation.ps1` at the repository root uses DeepSeek for
intent understanding and dialogue decisions, and pretrained LambdaMART for
reranking. [`submission_agent.py`](submission_agent.py) exports `Agent`.

## Modules

| Directory | Responsibility |
|---|---|
| `src/shopping_agent/understanding/` | LLM intent parsing and state updates |
| `src/shopping_agent/retrieval/` | Dynamic multi-channel retrieval, fusion, and constraint filtering |
| `src/shopping_agent/ranking/` | LambdaMART reranking and feature extraction |
| `src/shopping_agent/dialogue/` | Follow-up questions and response decisions |
| `src/shopping_agent/orchestration/` | LangGraph execution flow |
| `src/shopping_agent/application/` | Multi-turn session interface |
| `scripts/` | Evaluation, trace export, and training tools |
| `models/lambdamart_synthetic_2000/` | Active weights and feature metadata |

[Architecture](docs/agent_architecture.md) · [Component interfaces](docs/contracts/component_interfaces.md) ·
[Historical training](docs/lambdamart_training.md) · [MRR loss experiment](docs/mrr_training.md) ·
[Data format](data/README.md) · [Code tests](../docs/TESTING.md)
