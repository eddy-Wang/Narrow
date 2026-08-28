# Shopping Agent 团队架构与协作手册

> 文档定位：项目根目录的团队入口文档  
> 适用对象：算法、Agent、检索、后端、评测及新加入项目的成员  
> 当前状态：主链路已经成型，模块边界已经完成第一轮重构；后续工作以替换和增强各能力模块为主

## 1. 这份文档解决什么问题

本项目已经不再是“根据评测器固定提问”的脚本，而是一套面向真实用户的多轮购物 Agent。它需要在每一轮同时完成以下工作：

1. 理解用户的自然语言，而不是依赖评测器预先定义的采访顺序。
2. 把用户意图转成可计算、可维护的结构化状态。
3. 生成一句紧凑、适合语义检索的 `semantic_query`。
4. 同时执行关键词、语义和属性检索，再合并候选商品。
5. 根据当前候选集决定是否以及应该追问什么。
6. 返回自然语言消息、结构化追问字段和最多 10 个推荐结果。
7. 保留完整对话、状态变化和逐节点处理记录，以便调试和跑分分析。

这份文档是团队理解代码、拆分工作和提交改动时的第一入口。更细的接口约束和比赛规则仍以 `docs/` 下的专项文档为准。

## 2. 当前结论：架构是否已经成型

当前架构已经具备稳定的主干，可以支持多人并行开发：

- 产品入口与比赛接口已经分开。
- Agent 主链路已经由 LangGraph 明确编排。
- 用户理解、状态维护、检索、排序、问询、输出、基础设施和可观测性已经分包。
- 向量检索器和排序器已经有可替换接口。
- 旧导入路径通过兼容层保留，不要求一次性修改所有历史调用方。
- 测试已经按单元、集成和回归三个层级组织。
- 每次完整运行可以保留对话、节点 Trace、指标和配置。

“架构成型”不等于所有算法已经达到最佳效果。当前最重要的后续工作是增强各能力模块，尤其是语义检索、排序、候选驱动问询策略和线上持久化，而不是继续大幅调整目录。

## 3. 系统的完整运行链路

```text
真实用户 / 产品 UI
        │
        │ start_session() / chat()
        ▼
application.service.ShoppingAgent
        │
        ▼
understand_user
  LLM 主解释器 + 本地规则兜底
        │
        ├── 结构化 StatePatch
        └── 精简 semantic_query
        ▼
validate_patch → update_state → build_query
        │
        ├──────────────┬──────────────────┐
        ▼              ▼                  ▼
 lexical_retrieve  dense_retrieve   attribute_retrieve
        └──────────────┴──────────────────┘
                       ▼
                   rrf_fusion
                       ▼
                constraint_filter
                       │
          候选不足？───┴───候选充足？
              │                  │
              ▼                  │
      relax_and_backfill         │
              └──────────┬───────┘
                         ▼
                  rerank_fallback
                         ▼
              information_gain_question
                         ▼
                  build_response
                         ▼
                 validate_response
                         │
                         ▼
     message + ask_attribute + recommendations + usage
```

比赛评测器走的是同一条核心链路，只在入口处通过 `CompetitionAgent` 把 `reset/respond` 请求转换成产品服务调用。因此产品逻辑不应该为评测器写特殊分支。

## 4. 根目录结构

```text
techjam-conversational-search/
├─ src/shopping_agent/       Agent 产品代码
├─ starter/                  比赛要求的 Agent 入口
├─ evaluator/                本地公开集评测器
├─ tests/                    单元、集成和行为回归测试
├─ scripts/                  冒烟、LLM 评测和 Trace 评测脚本
├─ data/                     商品目录与公开评测数据
├─ docs/                     架构、接口、比赛规则和实验说明
├─ evaluation_runs/          按时间戳保存的完整运行产物
├─ pyproject.toml            Python 依赖、构建和测试配置
├─ langgraph.json            LangGraph Studio 配置
├─ README.md                 对外项目说明和常用命令
└─ TEAM_ARCHITECTURE_GUIDE.md 本文档
```

### 哪些目录可以修改

- 日常功能开发主要修改 `src/shopping_agent/` 和 `tests/`。
- 新的实验运行脚本放在 `scripts/`。
- 新的架构决策、接口说明和实验结论放在 `docs/`。
- `evaluation_runs/` 是运行产物，不应在其中手工维护业务逻辑。
- 不要为了提高公开集成绩修改 `evaluator/` 或公开标签。
- `starter/agent.py` 只负责暴露比赛需要的 Agent，不应复制核心算法。

## 5. `src/shopping_agent` 模块职责

```text
src/shopping_agent/
├─ application/
│  ├─ service.py                 面向真实用户的会话服务
│  └─ competition_adapter.py     比赛 reset/respond 适配器
├─ orchestration/
│  ├─ graph.py                   LangGraph 拓扑和依赖装配
│  ├─ nodes.py                   节点间数据协调
│  └─ routing.py                 条件路由
├─ domain/
│  ├─ schemas.py                 Constraint、AgentTurn 等稳定模型
│  ├─ state.py                   ShoppingState 全量状态定义
│  ├─ intent.py                  意图相关领域工具
│  └─ product_text.py            商品文本标准化
├─ understanding/
│  ├─ interpreter.py             LLM/规则解释器入口
│  ├─ state_patch.py             意图增量模型及状态合并规则
│  ├─ fallback_parser.py         无 LLM 或 LLM 失败时的本地解析
│  └─ prompts.py                 LLM 提示词
├─ retrieval/
│  ├─ interfaces.py             SemanticRetriever 协议
│  ├─ lexical.py                关键词检索和 CatalogIndex
│  ├─ semantic.py               当前本地语义检索实现
│  ├─ attributes.py             属性倒排检索
│  ├─ fusion.py                 多路候选融合
│  └─ engine.py                 历史导入兼容出口
├─ ranking/
│  ├─ interfaces.py             CandidateRanker 协议
│  └─ fallback.py               当前本地排序实现
├─ dialogue/
│  ├─ question_policy.py         基于候选集的信息增益问询
│  └─ response_builder.py        用户可见回复构造
├─ infrastructure/
│  ├─ llm/deepseek.py            DeepSeek/OpenAI-compatible 客户端
│  ├─ vector_store/              外部向量库适配器预留位置
│  └─ persistence/               生产持久化适配器预留位置
├─ observability/
│  └─ tracing.py                 从 checkpoint 重建逐节点 Trace
├─ studio.py                     LangGraph Studio 图入口
└─ 兼容模块                      agent.py、graph.py、schemas.py 等
```

### 5.1 `application`：产品入口

`ShoppingAgent` 是产品侧优先使用的入口，负责：

- 创建和释放会话。
- 维护外部 `session_id` 到 LangGraph `thread_id` 的映射。
- 自动维护轮次。
- 调用 Graph。
- 规范化推荐结果。
- 暴露当前意图状态和本轮 Trace。

推荐调用方式：

```python
from shopping_agent.application.service import ShoppingAgent

agent = ShoppingAgent(catalog_path="data/catalog.jsonl")
session_id = agent.start_session(user_profile={})

result = agent.chat(
    session_id,
    "我想找一双适合夏天通勤的黑色女鞋，预算 500 元以内",
    top_k=10,
)

intent_state = agent.get_intent_state(session_id)
turn_trace = agent.get_turn_trace(session_id, turn=1)
agent.release_session(session_id)
```

`CompetitionAgent` 只处理比赛的 `reset/respond` 形状。产品 UI、API 或 Demo 不应直接依赖评测器入口。

### 5.2 `orchestration`：主链路编排

`orchestration/graph.py` 只负责以下事情：

- 创建依赖实例。
- 注册节点。
- 声明节点之间的边。
- 声明候选不足时的条件路由。
- 注入 checkpointer、语义检索器和排序器。

它不应该包含解析、检索或排序算法。具体节点方法集中在 `ShoppingGraphNodes`，但节点也只做组件协调和状态读写，不应直接调用供应商 SDK。

节点名称被 Trace 和评测产物引用，属于稳定标识。重命名节点需要同步迁移 Trace 读取和历史对比逻辑。

### 5.3 `domain`：稳定领域模型

领域层定义跨模块共享的语言：

- `Constraint`：一个结构化约束。
- `AgentTurn`：一个标准 Agent 返回轮次。
- `ShoppingState`：Graph 全部可维护状态。
- 商品文本和意图的纯函数工具。

领域层必须保持纯净，不应导入 LangGraph、DeepSeek SDK、评测器或脚本。

### 5.4 `understanding`：用户语义理解

这一层的核心输出不是商品，而是一个受约束的 `StatePatch`。LLM 只能表达“用户想如何修改当前诉求”，不能在这一阶段检索商品或编造 `parent_asin`。

LLM 可用时，以 LLM 解释为主；供应商关闭、请求失败或输出不合法时，使用本地规则解析器兜底。无论来自哪一种解析器，输出都必须经过统一校验和归一化。

### 5.5 `retrieval`：候选召回

当前同时使用三路召回：

- `lexical`：适合品牌、明确商品词、精确描述等词面匹配。
- `semantic`：使用精简语义查询寻找意思相近的商品。
- `attributes`：使用类别、材质、颜色、尺码、预算等结构化信息召回。

三路结果通过 Reciprocal Rank Fusion 合并。候选标识统一使用 `parent_asin`，各路可以添加自己的排名或分数字段，但不得改变候选身份语义。

### 5.6 `ranking`：精排

排序器接收已经融合和过滤的候选，并结合：

- 语义查询。
- 商品类别。
- 当前有效约束。
- 用户 Profile。
- 已经推荐过的商品。

返回按优先级从高到低排列的候选。当前提供本地 `FallbackReranker`，后续可以无侵入接入 Cross Encoder、外部重排服务或 LLM reranker。

### 5.7 `dialogue`：追问与回复

问询不根据“第几轮应该问品牌”这样的固定表执行，而是基于本轮候选集：

- 观察候选在各属性上的分布。
- 估算某个问题能否有效切分候选。
- 避免重复询问已经回答或明确表示无偏好的字段。
- 生成 `ask_attribute`、问题选项和用户可见问题。

回复构造器再把问询与推荐结果合成为自然语言响应。

### 5.8 `infrastructure`：外部能力适配

这一层放置供应商和存储细节，例如：

- DeepSeek 客户端及鉴权。
- Qdrant、Milvus、Pinecone、pgvector 等向量库实现。
- Redis、PostgreSQL 或其他 Checkpoint/Persistence 实现。

上层只能依赖协议或抽象，不应散落供应商 SDK 调用。

### 5.9 `observability`：可观测性

Trace 不是主链路算法的一部分。`observability/tracing.py` 从 LangGraph checkpoint 重建节点写入，供调试、评测和展示使用。

把 Trace 独立出来的好处是：线上服务可以选择轻量记录，离线评测可以保留完整记录，而不会污染 Agent 的业务返回。

## 6. 核心数据模型

### 6.1 `Constraint`

每个用户限制都表示为结构化约束：

```json
{
  "field": "color",
  "operator": "contains",
  "value": "black",
  "strength": "soft",
  "confidence": 0.95,
  "source_turn": 1
}
```

字段说明：

| 字段 | 作用 |
|---|---|
| `field` | 类别、材质、颜色、尺码、风格、品牌、预算、功能、使用场景等 |
| `operator` | `contains`、`not_contains`、`eq`、`lte`、`gte` |
| `value` | 字符串或数值 |
| `strength` | `hard` 表示不可违背，`soft` 表示排序偏好 |
| `confidence` | 解析可信度，范围 0 到 1 |
| `source_turn` | 约束来自哪一轮，便于追踪和覆盖 |

### 6.2 `StatePatch`

`StatePatch` 表示“这一轮对已有诉求的增量修改”，不是完整会话状态。典型输出：

```json
{
  "action": "add",
  "category": "women shoes",
  "constraints": [
    {
      "field": "color",
      "operator": "contains",
      "value": "black",
      "strength": "soft",
      "confidence": 0.95,
      "source_turn": 1
    },
    {
      "field": "budget",
      "operator": "lte",
      "value": 500,
      "strength": "hard",
      "confidence": 0.98,
      "source_turn": 1
    }
  ],
  "remove_fields": [],
  "no_preference": [],
  "retire_soft": false,
  "semantic_query": "black women's shoes for summer commuting under 500",
  "intent_summary": "用户需要夏季通勤女鞋，偏好黑色，预算不超过 500",
  "language": "zh",
  "confidence": 0.94,
  "parser": "deepseek",
  "fallback_reasons": []
}
```

`action` 的语义：

| 动作 | 含义 |
|---|---|
| `add` | 在现有诉求上增加信息 |
| `replace` | 替换相同字段的旧约束，例如“不要黑色了，换白色” |
| `remove` | 删除指定字段的限制 |
| `no_preference` | 用户明确表示某个属性无所谓 |

`validate_state_patch` 会完成去重、空值清理、非法预算清理以及同值正负约束冲突处理。`apply_state_patch` 会把被替换或移除的约束放入 `superseded_constraints`，从而保留可解释的状态历史。

### 6.3 `ShoppingState`

Graph 状态可以按职责分成六组：

| 分组 | 主要字段 |
|---|---|
| 会话输入 | `session_id`、`turn`、`top_k`、`user_message`、`user_profile` |
| 长期意图 | `category`、`active_constraints`、`superseded_constraints`、`no_preference`、`asked_attributes` |
| 理解结果 | `semantic_patch`、`semantic_confidence`、`semantic_fallback_reasons`、`semantic_query`、`intent_summary`、`user_language` |
| 检索过程 | `lexical_query`、三路 candidates、`fused_candidates`、`filtered_candidates`、`ranked_candidates` |
| 对话输出 | `ask_attribute`、`question_scores`、`question_options`、`response_message`、`recommendations` |
| 诊断信息 | `retrieval_attempt`、`constraints_relaxed`、`candidate_count`、`usage`、`errors` |

Checkpoint 中只保存可序列化的字典、列表、字符串和数字，不保存任意应用对象。这是未来切换远程持久化的基础。

## 7. 一轮请求中每个节点做什么

| 节点 | 主要输入 | 主要输出 | 责任边界 |
|---|---|---|---|
| `understand_user` | 最新消息、历史意图、Profile | 原始 `semantic_patch`、usage | 调用解释器，不检索商品 |
| `validate_patch` | 原始 patch | 归一化 patch、错误或兜底信息 | 保证结构合法 |
| `update_state` | 旧状态、有效 patch | 当前约束、被替代约束、查询摘要 | 维护多轮诉求 |
| `build_query` | 当前意图 | lexical/search query | 为各检索路由准备查询 |
| `lexical_retrieve` | lexical query | `lexical_candidates` | 词面召回 |
| `dense_retrieve_fallback` | semantic query | `dense_candidates` | 语义召回 |
| `attribute_retrieve` | 类别和约束 | `attribute_candidates` | 结构化属性召回 |
| `rrf_fusion` | 三路候选 | `fused_candidates` | 去重并融合排名 |
| `constraint_filter` | 融合候选、hard constraints | `filtered_candidates` | 执行硬约束 |
| `relax_and_backfill` | 候选不足的结果 | 补全候选、放宽标记 | 防止结果集为空或太少 |
| `rerank_fallback` | 过滤后候选及完整意图 | `ranked_candidates` | 精排并减少重复推荐 |
| `information_gain_question` | 当前候选分布、已问字段 | 问题字段、分数、选项 | 决定最有价值的追问 |
| `build_response` | 排序结果、问题决策、语言 | 消息与推荐列表 | 构造用户可见输出 |
| `validate_response` | 草拟输出 | 合法最终输出 | 去重、截断和协议校验 |

如果节点需要一个新字段，应先把字段加入 `ShoppingState`，说明它的生产者和消费者，并补充 Trace/测试。不要通过隐式对象属性在节点间传递信息。

## 8. 结构化粗筛与语义查询如何配合

用户的一句话会同时产生两种表达：

### 结构化表达

用于精确过滤、属性召回和状态覆盖，例如：

```text
category = women shoes
color contains black
budget <= 500
use_case contains commuting
```

它的优点是可解释、可维护、适合硬约束；缺点是难以完整表达“有质感”“适合旅行但不要太运动”等复杂语义。

### 语义表达

用于向量查询，例如：

```text
elegant lightweight black women's shoes for summer commuting under 500
```

它应是一句完整、精简、消歧后的查询，包含当前仍然有效的整体诉求，而不是只复述最新一句用户消息。它不应包含对话礼貌用语、解析过程或无关历史。

两种表达不能互相替代：结构化信息负责“必须满足什么”，语义查询负责“整体上像什么”。最终召回需要两者共同参与。

## 9. 多轮诉求状态维护

状态维护需要覆盖以下真实对话：

### 增加约束

```text
用户：我想要一双跑鞋。
用户：最好是黑色，雨天也能穿。
```

第二轮应保留“跑鞋”，并增加颜色和防水/使用场景约束。

### 替换约束

```text
用户：预算 100 美元以内。
用户：预算可以提高到 150。
```

旧预算应进入 `superseded_constraints`，当前只保留新的上限。

### 否定约束

```text
用户：不要皮革材质。
```

应得到 `material not_contains leather`，不能错误地当成正向偏好。

### 明确无偏好

```text
Agent：对品牌有偏好吗？
用户：品牌无所谓。
```

`brand` 应进入 `no_preference`，清除品牌约束，并避免下一轮再次询问品牌。

### 意图切换

```text
用户：算了，不买鞋了，我想看双肩包。
```

应更新类别并按 patch 策略退休不再适用的软约束。是否保留预算等跨类别约束由解释器明确输出，而不应由检索层猜测。

## 10. 可替换接口

### 10.1 语义检索器

任何新的向量数据库适配器都实现：

```python
from typing import Any, Protocol

class SemanticRetriever(Protocol):
    def search(self, query: str, limit: int = 200) -> list[dict[str, Any]]:
        ...
```

最低要求：

- 返回列表。
- 每个候选包含非空 `parent_asin`。
- 不修改 Agent 状态。
- 不直接决定最终推荐。
- 失败策略明确：抛出可识别异常或返回空列表，由上层进行兜底。

注入方式：

```python
graph = build_shopping_graph(
    catalog_path="data/catalog.jsonl",
    semantic_retriever=my_vector_retriever,
)
```

### 10.2 候选排序器

新的排序实现需要符合 `CandidateRanker.rank`：

```python
rank(
    candidates,
    *,
    query,
    category,
    constraints,
    profile=None,
    previously_recommended=None,
)
```

返回结果必须按最好到最差排序，保留 `parent_asin`，建议写入 `reranker_score` 以便 Trace 和实验对比。

### 10.3 Checkpointer

本地默认使用 `InMemorySaver`。生产部署时应注入持久化 Checkpointer，保证：

- 多实例服务间可以恢复会话。
- 服务重启后用户状态不会丢失。
- 会话具有合理 TTL。
- 敏感 Profile 有明确的数据保留和删除策略。
- Trace 与产品日志区分存储权限。

## 11. 公共 API 与比赛 API

### 产品 API

```python
session_id = agent.start_session(user_profile={})
result = agent.chat(session_id, "想找一个通勤包", top_k=10)
```

返回：

```json
{
  "message": "你更偏好托特包还是双肩包？",
  "ask_attribute": "style",
  "recommendations": [
    {"parent_asin": "B000...", "score": 0.83}
  ],
  "usage": {
    "prompt_tokens": 320,
    "completion_tokens": 95
  }
}
```

### 比赛 API

```python
agent.reset(session_id, user_profile)
result = agent.respond(session_id, user_message, turn=1, top_k=10)
```

比赛适配器与产品 API 必须输出相同语义。不得为公开评测 session 或 target 写硬编码逻辑。

## 12. Trace 与评测产物

运行完整 Trace 评测：

```bash
uv run python scripts/evaluate_with_traces.py --llm --candidate-limit 20
```

每次运行写入：

```text
evaluation_runs/<timestamp>/
├─ config.json             本次运行配置
├─ summary.json            聚合指标和统计
├─ sessions.jsonl          session 级元数据/结果
├─ conversations.jsonl     每轮用户与 Agent 对话
├─ node_traces.jsonl       每轮逐节点写入和紧凑状态差异
├─ report.md               人类可读报告
└─ analysis.md             补充分析（如果该次运行生成）
```

`evaluation_runs/LATEST.txt` 指向最近一次运行。分析跑分时至少同时查看：

- 最终总分和分场景指标。
- 首次命中的轮次。
- 目标商品在各召回通道的排名变化。
- StatePatch 是否正确理解否定、替换和预算。
- 候选经过 filter/relax/rerank 后如何变化。
- 每轮为什么询问某个属性。
- LLM 是否触发 fallback。
- token 和延迟是否异常。

不要只看总分。一个检索改动即使总分略高，也可能破坏意图切换或边界场景，需要回归测试和逐 session 对比确认。

## 13. 当前可复现基线

在本次目录重构完成后，核心行为保持不变：

| 运行方式 | HitRate@10 | MRR | MTTC | Technical Score |
|---|---:|---:|---:|---:|
| 200 条公开集，本地兜底链路 | 0.8200 | 0.329188 | 4.005 | 0.648656 |
| 已保存的 DeepSeek Trace 运行 | 0.9000 | 0.362373 | 3.305 | 0.712612 |

DeepSeek 运行产物位于 `evaluation_runs/20260827_232525_+0800/`。它包含 200 个会话、641 个对话轮次和 7039 条节点记录，可作为观察 Agent 行为的样本。

注意：公开集分数用于工程迭代，不代表私有集成绩。任何实验都应记录代码版本、模型、参数、数据版本和是否启用 LLM，避免不可比较的“口头分数”。

## 14. 测试分层

```text
tests/
├─ unit/
│  └─ test_package_boundaries.py
├─ integration/
│  └─ test_evaluator.py
└─ regression/
   └─ test_agent_behavior.py
```

### 单元测试

验证纯函数、数据模型、接口约束和依赖边界。应快速、确定，不调用真实 LLM 或远程向量库。

### 集成测试

验证组件装配、比赛适配器和评测器之间能否正确工作。

### 回归测试

验证多轮 Agent 行为，例如否定、状态覆盖、无偏好、问询去重和推荐协议。修复一个 Agent 行为 Bug 时，应先或同时添加能复现它的回归用例。

常用命令：

```bash
uv sync --group dev
uv run pytest
uv run python -m evaluator.local_evaluator
```

启用可选 DeepSeek SDK：

```bash
uv sync --extra deepseek --group dev
```

只跑某一层：

```bash
uv run pytest tests/unit
uv run pytest tests/integration
uv run pytest tests/regression
```

## 15. 本地开发和运行

### 15.1 环境要求

- Python `>=3.12,<3.13`。
- 推荐使用 `uv` 管理依赖。
- 商品目录默认位于 `data/catalog.jsonl`。
- API Key 只能放在 `.env` 或系统环境变量中，禁止提交到 Git。

### 15.2 开启 LLM

在 `.env` 中设置：

```dotenv
SHOPPING_AGENT_ENABLE_LLM=true
DEEPSEEK_API_KEY=your_key_here
```

默认模型是 `deepseek-v4-flash`。供应商不可用时，系统应保留本地解析兜底，不能让整条购物链路崩溃。

供应商冒烟：

```bash
uv run python scripts/smoke_deepseek.py
```

完整 API 评测：

```bash
uv run python scripts/evaluate_with_deepseek.py --output results.json
```

### 15.3 LangGraph Studio

```bash
uv run langgraph dev
```

Windows PowerShell 推荐先设置 UTF-8 和项目内缓存：

```powershell
$env:PYTHONUTF8 = "1"
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv run langgraph dev
```

Studio 适合观察节点图、输入状态和单轮执行；批量行为与分数仍以 Trace 评测脚本为准。

## 16. 团队分工建议

可以按稳定能力边界分配负责人：

| 小组/负责人 | 主要路径 | 交付物 | 需要重点对齐的人 |
|---|---|---|---|
| 意图理解与状态 | `domain/`、`understanding/` | StatePatch、Prompt、解析回归集 | 编排、对话策略 |
| 检索 | `retrieval/`、`infrastructure/vector_store/` | 多路召回、向量库、召回指标 | 排序、数据 |
| 排序 | `ranking/` | reranker、特征和离线对比 | 检索、评测 |
| 问询与回复 | `dialogue/` | 信息增益策略、自然语言输出 | 意图理解、产品 |
| Agent 编排 | `orchestration/` | 图拓扑、路由、节点状态契约 | 所有能力负责人 |
| 产品与 API | `application/` | 会话服务、外部 API、生命周期 | 编排、基础设施 |
| 评测与可观测性 | `observability/`、`scripts/`、`tests/` | Trace、跑分、回归集 | 所有人 |
| 基础设施 | `infrastructure/` | LLM、向量库、持久化适配 | 产品、检索、理解 |

每个稳定接口至少指定一位主 Reviewer。修改 `StatePatch`、`ShoppingState`、`SemanticRetriever`、`CandidateRanker`、节点名称或公共响应格式时，生产者和消费者双方都应 Review。

## 17. 依赖方向

```text
application
    ↓
orchestration ─────────→ observability
    ↓
understanding / retrieval / ranking / dialogue
    ↓
domain

infrastructure ──实现上层需要的外部能力接口
```

必须遵守的规则：

1. `domain` 不依赖任何上层包。
2. `retrieval` 和 `ranking` 不导入 `orchestration`。
3. `graph.py` 不实现具体算法。
4. 节点方法不直接写供应商 SDK 调用。
5. 比赛评测器不进入产品核心包。
6. 顶层兼容模块只做 re-export，不添加新逻辑。
7. 跨模块共享数据使用显式 Schema 或 Protocol，不传递未约定的动态对象。

## 18. 兼容层与新代码导入规则

为避免重构一次性破坏已有代码，目前保留了旧入口：

| 历史导入 | 新代码应使用 |
|---|---|
| `shopping_agent.agent` | `shopping_agent.application.service` |
| `shopping_agent.graph` | `shopping_agent.orchestration.graph` |
| `shopping_agent.schemas` | `shopping_agent.domain.schemas` |
| `shopping_agent.state` | `shopping_agent.domain.state` |
| `shopping_agent.intent` | `shopping_agent.domain.intent` |
| `shopping_agent.semantic_state` | `shopping_agent.understanding.state_patch` 等实际模块 |
| `shopping_agent.catalog` | `shopping_agent.retrieval.lexical` |
| `shopping_agent.question_policy` | `shopping_agent.dialogue.question_policy` |
| `shopping_agent.retrieval.engine` | 对应的 `retrieval` 专项模块 |

兼容模块用于过渡，不是继续堆积功能的地方。新增代码必须直接引用新的分层路径。

## 19. 常见扩展方式

### 接入真正的向量数据库

1. 在 `infrastructure/vector_store/` 新建适配器。
2. 实现 `SemanticRetriever.search`。
3. 保证候选包含 `parent_asin`。
4. 为超时、空查询和供应商错误添加测试。
5. 通过 `build_shopping_graph(..., semantic_retriever=...)` 注入。
6. 分别比较 Dense 路由召回率、最终 HitRate/MRR/MTTC 和耗时。
7. 保存完整 Trace，确认提升不是由数据泄漏或异常放宽导致。

### 接入新的 Reranker

1. 在 `ranking/` 增加实现。
2. 实现 `CandidateRanker.rank`。
3. 不修改候选 `parent_asin`。
4. 明确分数方向和字段名。
5. 注入 Graph，不在节点内写模型分支。
6. 对比排序前后目标排名、重复推荐率、延迟和成本。

### 更换 LLM 供应商

1. 在 `infrastructure/llm/` 新增客户端适配。
2. 保持 Understanding 层输出仍为 `StatePatch`。
3. 做 JSON/Schema 校验，不能信任原始模型输出。
4. 记录 provider、model、token、latency 和 fallback reason。
5. 加入超时、限流和无效输出的兜底测试。
6. 不把 API Key、完整敏感 Profile 或供应商响应直接写入公开产物。

### 增加新的追问策略

1. 在 `dialogue/` 实现，不放进评测器或 Graph 拓扑文件。
2. 只使用当前候选、当前状态和历史已问字段。
3. 输出合法 `ask_attribute`。
4. 避免询问用户已回答或明确无偏好的字段。
5. 评估问题覆盖率、重复率、回答后的候选缩减和首次命中轮次。

## 20. 团队开发流程

建议每项功能按照以下顺序推进：

1. 写清楚要提升的能力和目标指标。
2. 确定修改属于哪个模块，是否触碰稳定接口。
3. 先准备最小行为样例或回归测试。
4. 在模块内部完成实现，通过依赖注入接入主链路。
5. 运行单元和行为回归测试。
6. 跑公开集本地基线；涉及 LLM 时再跑带 Trace 的小样本和完整集。
7. 对比失败 session，而不只对比聚合总分。
8. 在 `docs/experiments/` 记录值得保留的实验结论。
9. PR 中说明接口变化、指标变化、成本变化和回滚方式。

### PR 最低检查清单

- [ ] 修改位于正确模块，没有把算法写进 `graph.py`。
- [ ] 新代码使用新包路径，没有向兼容层添加逻辑。
- [ ] 新增或修改行为有测试。
- [ ] `uv run pytest` 通过。
- [ ] 公共返回仍满足最多 10 个、唯一且合法的 `parent_asin`。
- [ ] 多轮状态不会意外丢失已有约束。
- [ ] LLM 或外部服务失败时仍有清晰兜底。
- [ ] 日志和 Trace 不包含 API Key。
- [ ] 跑分说明包含配置和可复现命令。
- [ ] 如果修改稳定接口，已由生产者和消费者负责人 Review。

## 21. 当前已知问题与优先级

### P0：保证主链路可靠

- 所有供应商调用必须超时可控并能 fallback。
- 状态替换、否定、无偏好和意图切换不能回归。
- 推荐必须合法、去重并限制为最多 10 个。
- Trace 和评测产物必须可复现。

### P1：提升候选驱动问询

已保存的 DeepSeek 公开集运行中，首轮问题有 199/200 次选择了品牌。这说明虽然问询已经使用候选集计算，但属性效用、缺失值处理或分数校准仍有明显偏置。下一阶段应重点：

- 检查品牌字段是否天然更完整，从而错误获得高信息增益。
- 对问题成本、用户可回答性和已知意图增加惩罚/奖励。
- 用“回答后候选减少量”和“首次命中提升”评估问题，而不是只看熵。
- 建立覆盖真实中文表达的追问回归集。

### P1：接入生产级语义检索

当前 `LocalDenseIndex` 是可用兜底，不是最终向量数据库方案。需要完成离线 embedding、索引版本、增量更新、召回监控和远程失败降级。

### P1：增强排序

当前本地特征排序为可复现基线。后续应比较 Cross Encoder、学习排序或轻量 LLM rerank，同时严格评估延迟和成本。

### P2：生产持久化与 API

- 把内存 Checkpointer 换成持久化实现。
- 明确 session TTL、并发和幂等行为。
- 增加真实 HTTP/WebSocket 产品接口。
- 对用户 Profile 和 Trace 实施权限、脱敏和删除策略。

## 22. 新成员上手清单

1. 阅读本文档和根目录 `README.md`。
2. 阅读自己负责模块的代码以及 `docs/contracts/component_interfaces.md`。
3. 执行 `uv sync --group dev`。
4. 执行 `uv run pytest`，确认本地环境正常。
5. 执行一次 `uv run python -m evaluator.local_evaluator`。
6. 打开一份 `evaluation_runs/` 中的 `report.md` 和 `node_traces.jsonl`。
7. 在 Studio 中运行一个包含状态替换或否定的多轮会话。
8. 与模块负责人确认稳定接口和实验指标后再开始较大改动。

## 23. 相关文档索引

| 文档 | 用途 |
|---|---|
| `README.md` | 项目对外介绍、安装和常用命令 |
| `docs/agent_architecture.md` | Agent 运行架构补充说明 |
| `docs/architecture/module_boundaries.md` | 模块所有权和依赖规则 |
| `docs/contracts/component_interfaces.md` | 稳定组件接口 |
| `docs/experiments/README.md` | 实验记录规范 |
| `docs/competition_specification.md` | 比赛任务和指标定义 |
| `docs/agent_api_contract.json` | 机器可读 Agent 接口 |
| `docs/evaluation_config.json` | 评测配置 |
| `docs/baseline_results.json` | 官方弱基线结果 |
| `docs/submission_rules.md` | 提交规则 |
| `PROJECT_HANDOFF.md` | 历史交接信息 |
| `DATA_ATTRIBUTION.md` | 数据来源和使用说明 |

## 24. 最后需要统一的共识

团队后续开发应围绕一条稳定主线展开：

```text
自然语言输入
→ LLM/规则理解
→ 结构化状态更新 + 完整语义查询
→ 多路召回
→ 约束过滤和精排
→ 基于当前候选的有效追问
→ 可解释、可追踪的推荐输出
```

目录结构的目标不是追求层次越多越好，而是让不同成员能够在明确边界内并行迭代。只要公共状态、协议和节点语义保持稳定，理解、检索、排序、问询和基础设施都可以独立升级，并通过同一套回归测试与 Trace 评测验证效果。
