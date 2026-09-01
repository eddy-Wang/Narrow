# Narrow 购物 Agent

本包包含 Narrow 的检索、状态管理、排序与对话运行时。默认在线链路使用
OpenAI Responses API，并通过 Structured Outputs 生成经过校验的状态更新与
对话决策。

## 安装

```bash
uv sync --extra web --extra ltr --extra openai --group dev
cp .env.example .env
```

在 `.env` 中设置 `OPENAI_API_KEY`，然后启动本地 API：

```bash
uv run --extra web python -m shopping_agent.web
```

项目保留确定性的本地回退，便于开发和测试。完整启动方式见
[根目录 README](../README.zh-CN.md)，评估方法见 [测试文档](../docs/TESTING.zh-CN.md)。

## 核心链路

1. 根据当前会话状态校验结构化 StatePatch。
2. 将有效约束与用户画像信号组合为 Canonical Query。
3. 按动态策略执行关键词、稠密向量和属性三路召回。
4. 应用硬约束、软加权、未知属性保留、放宽与融合。
5. 精排候选，并在需要时选择信息增益最高的追问。

`agent.py` 导出兼容入口，可将运行时嵌入外部评估器或应用。
