# Narrow

[English](README.md) · [项目指南](docs/PROJECT_GUIDE.md) · [贡献指南](CONTRIBUTING.md)

Narrow 是一个开源的多轮对话商品搜索引擎，面向需要持续维护用户意图的应用。
它将 OpenAI Responses API 与结构化状态管理、动态多路召回、约束处理和
Learning-to-Rank 组合在同一条可追踪的执行链路中。

系统不会把每条消息当作一次全新的搜索。用户可以追加预算、替换品牌偏好、
撤销旧条件或回答澄清问题，而不丢失仍然有效的历史需求。

## 核心能力

- **可执行状态**：经过校验的 StatePatch 更新 active、superseded 和
  no-preference slots，并直接控制下一轮搜索。
- **动态检索策略**：购买、浏览和意图不完整的请求会获得不同的关键词、
  向量和属性检索权重与候选深度。
- **约束感知排序**：分别处理硬条件、软偏好、未知属性和候选回填。
- **有价值的追问**：信息增益和当前证据共同决定推荐还是只追问一个关键属性。
- **完整可观测性**：Trace 展示状态变化、检索路由、候选集、约束和最终排序。
- **可复现评测**：包含离线测试、场景模拟器、排名指标和 Trace 故障分析。

## 快速开始

需要 Python 3.12、[uv](https://docs.astral.sh/uv/) 和 OpenAI API Key。

```bash
git clone https://github.com/eddy-Wang/Narrow.git
cd Narrow
uv sync --locked --project narrow-shopping-agent \
  --extra web --extra ltr --extra openai --group dev
cp narrow-shopping-agent/.env.example narrow-shopping-agent/.env
```

编辑 `narrow-shopping-agent/.env`：

```dotenv
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-5.5
OPENAI_REASONING_EFFORT=low
SHOPPING_LLM_PROVIDER=openai
SHOPPING_AGENT_ENABLE_LLM=true
SHOPPING_DENSE_BACKEND=local
LANGSMITH_TRACING=false
```

API Key 只保存在服务端，请勿提交 `.env`。

## 准备商品数据

将 JSONL 商品目录放在 `narrow-shopping-agent/data/catalog.jsonl`。每行至少包含
稳定的 `parent_asin` 和可搜索文本；category、price、brand、color、size 等
结构化属性可以提高过滤与排序质量。具体格式见
[数据指南](narrow-shopping-agent/data/README.md)。

仓库不重新分发生产商品目录。使用者需要自行确认数据来源、许可证和使用条款。

## 启动 API

```bash
cd narrow-shopping-agent
uv run --extra web --extra ltr --extra openai python -m shopping_agent.web
```

## 启动可视化工作台

```bash
npm --prefix demo-frontend ci --no-audit --no-fund
npm --prefix trace-visualizer ci --no-audit --no-fund
./scripts/run_demo.sh --skip-install
```

- Shopping workbench：`http://127.0.0.1:5173`
- Agent API：`http://127.0.0.1:8000`
- Trace viewer：`http://127.0.0.1:3000`

## 测试

```bash
uv run --project narrow-shopping-agent --group dev pytest -q
npm --prefix demo-frontend test -- --run
node --experimental-strip-types --test \
  trace-visualizer/scripts/tests/trace-format.test.mjs
```

在线测试需要显式配置 `OPENAI_API_KEY`；单元测试和回归测试默认使用确定性 Fake，
不会消耗 API credits。

## 参与维护

欢迎提交可复现问题、评测场景、检索后端、排序改进和文档修复。开发流程见
[CONTRIBUTING.md](CONTRIBUTING.md)，安全问题请参考 [SECURITY.md](SECURITY.md)。

## License

代码使用 [MIT License](LICENSE)。模型权重与外部数据可能有独立的来源或使用条款，
重新分发前请阅读相邻的 attribution 文件。
