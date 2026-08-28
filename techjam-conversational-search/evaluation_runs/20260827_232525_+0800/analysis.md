# Evaluation Analysis

Run: `20260827_232525_+0800`

## What changed with LLM-first intent understanding

| Metric | Local fallback | DeepSeek traced run | Change |
|---|---:|---:|---:|
| Hit Rate@10 | 0.820000 | 0.900000 | +0.080000 |
| MRR | 0.329188 | 0.362373 | +0.033185 |
| MTTC | 4.005000 | 3.305000 | -0.700000 |
| Technical Score | 0.648656 | 0.712612 | +0.063956 |

The LLM path materially improves recall and reaches the target earlier, but MRR
is still modest relative to Hit Rate. The target is often retrieved but not
ranked near the top, so reranking remains a major opportunity.

## Runtime profile

- 200 sessions, 641 turns, 180 hits, 20 misses.
- Average simulated conversation length: 3.205 turns.
- Mean Agent response latency: 1,428.3 ms.
- Median Agent response latency: 1,378.4 ms.
- P95 Agent response latency: 1,927.2 ms.
- Maximum Agent response latency: 3,268.3 ms.
- Prompt tokens: 477,292 (744.6 per turn).
- Completion tokens: 85,125 (132.8 per turn).
- Total tokens: 562,417 (877.4 per turn).

The 1,452.9-second wall time includes checkpoint reconstruction and writing a
32 MB node trace. It is not representative of production response latency.

## Trace integrity

- All 200 session records are present.
- All 641 conversation turns are present.
- 7,039 node-stage records are present.
- All 641 intent-understanding stages report `parser=deepseek`.
- No provider fallback was observed.
- Three turns in `public_0197` stopped during reranking because one catalog price
  was the string `—`. The run preserves these errors. The numeric-price guard was
  fixed after this baseline and has a regression test, but this run was not
  rewritten or rescored.

## Most important behavioral finding

The clarification policy asked about `brand` on 199 of 200 first turns. This is
mathematically understandable because brand has high entropy, but it produces
poor real-user questions involving obscure marketplace brands. Candidate entropy
alone is not an adequate measure of question utility.

Question counts across all turns:

| Attribute | Count |
|---|---:|
| brand | 200 |
| style | 89 |
| material | 70 |
| use_case | 64 |
| color | 62 |
| budget | 43 |
| no question | 113 |

The next policy should combine expected candidate reduction with user
answerability and business relevance. A practical default priority is use case,
category/shape, material, functional feature, size, style, budget, color, then
brand unless the user already mentioned a brand.

## Scenario observations

- Buying performs best on speed (`MTTC=2.4375`).
- Intent Override has the best ranking quality (`MRR=0.489854`) but naturally
  takes longer (`MTTC=5.0`) because the simulator changes intent mid-session.
- Boundary has a high hit rate (`0.9`) but the lowest MRR (`0.250397`), suggesting
  that no-preference answers do not help the current reranker focus.
- Browsing is the largest segment and has 9 misses, so it should dominate the
  next qualitative error review.

## Recommended next experiments

1. Replace raw entropy with a question-utility score that penalizes obscure or
   high-cardinality brands and rewards answerable attributes.
2. Track target presence and rank at lexical, semantic, attribute, fusion,
   filtering, and reranking stages to separate recall failures from ranking
   failures.
3. Replace the hashed semantic fallback with the intended embedding/vector DB
   implementation and compare route-level recall.
4. Add a learned or LLM reranker experiment; the current gap between Hit Rate
   and MRR indicates that candidate ordering is a bottleneck.

---

# 中文统一分析：问题、改进板块与团队任务拆分

> 本节把上面的跑分结论、逐轮对话检查和逐节点 Trace 检查合并为一份可直接用于团队分工的方案。
> 目标不是针对公开样本写特殊规则，而是通过失败案例定位可泛化的 Agent 能力缺陷。

## 一、这一轮实验说明了什么

本轮 200 个会话中有 180 个命中、20 个完全未命中，另有 7 个会话直到第 7～10 轮才命中。LLM-first 的用户理解使 HitRate、MRR 和 MTTC 都优于本地规则链路，说明“用 LLM 理解真实用户输入、生成结构化状态和语义查询”的方向有效。
但 `HitRate@10=0.90` 与 `MRR=0.362373` 之间仍有明显差距：不少目标商品已经被某条检索通道找到，却没有进入最终推荐前部。因此下一轮不能只继续扩大召回，也必须同时修复约束粗筛、候选融合、精排和问询。

本轮发现的十类问题，可以归并到五个大板块：

```text
板块一：语义理解与用户诉求状态
        ↓
板块二：检索、结构化粗筛与候选融合
        ↓
板块三：精排与最终推荐排序
        ↓
板块四：问询策略与对话回复
        ↓
板块五：数据可靠性、Trace、评测与主链路集成
```

## 二、本轮发现的十类具体问题

### 问题 1：控制语句、数字单位和属性被错误解析

已经观察到以下错误：

```text
Those options are not quite right yet. Ask me about one specific attribute.
```

被解析为：

```text
feature not_contains "quite right yet"
```

`public_0197` 中的：

```text
up to 30mm wide
```

被错误解析为：

```text
budget <= 30
```

部分会话还同时存在：

```text
color contains "color: black"
color contains "black"
```

说明当前理解层没有先区分商品需求和对话行为，数字解析也没有充分结合单位与上下文，约束规范化则仍停留在字符串级别。

### 问题 2：结构化硬约束没有真正完成粗筛

用户已经给出材质、颜色等硬约束后，候选数量仍然经常保持在 400～500。例如：

```text
black leather wallet
→ filtered_candidates = 435
```

当前实现为了避免商品元数据缺失造成误杀，对很多正向约束不会排除商品。这个原则有合理性，但现在缺少“明确匹配、元数据未知、明确冲突”的三态判断，导致 Schema 中的 `hard` 在执行中更像软加分。

### 问题 3：当前 Dense 语义召回能力较弱

在 20 个完全未命中的会话中，目标进入不同阶段 Trace Top 20 的情况是：

| 阶段 | 目标进入 Top 20 的失败会话数 |
|---|---:|
| Attribute Retrieval | 15/20 |
| Lexical Retrieval | 4/20 |
| Dense Retrieval | 1/20 |
| RRF Fusion | 6/20 |
| Constraint Filter | 5/20 |
| Final Reranking | 2/20 |

当前 `LocalDenseIndex` 是可复现的 Hash 特征兜底，不是真正的语义 Embedding，因此对模糊需求、同义表达和长尾商品的补充召回能力有限。

以下 5 个完全未命中样本没有进入任何已保存通道的 Top 20，更接近纯召回、查询构造或商品表达问题：

```text
public_0029
public_0074
public_0096
public_0161
public_0167
```

### 问题 4：属性召回找到的目标在融合阶段被淹没

属性召回在 15/20 个未命中会话中把目标送入 Top 20，但融合后只剩 6/20。说明属性通道已经做对了大量工作，损失却发生在 RRF 阶段。

主要原因包括：

- 不同 Route 的可靠性没有充分区分。
- 属性强命中没有保护机制。
- 每路头部候选没有保底。
- `route_count`、硬约束命中数和类别一致性权重不足。

### 问题 5：精排把已经找到的目标排掉

`public_0046` 是最典型的例子。第 3～4 轮目标曾经达到：

```text
Lexical Rank   = 1
Dense Rank     = 4
Attribute Rank = 1
Fusion Rank    = 1
Final Top 10   = 未出现
```

目标融合排名第一，却在 Reranker 后跌出 Trace Top 20。

检查候选后可以看到：

- 只要商品包含 `wool` 就获得较高得分。
- 羊毛帽子、羊毛衫、普通袜子等错误类别占据前排。
- 完整类别短语匹配过于严格。
- 类别不一致没有足够强的惩罚。
- 评论量等质量特征参与了错误候选之间的排序。

这属于确定性的排序问题，不是召回不足。

### 问题 6：问询策略严重偏向品牌

200 个会话中，199 个第一轮都询问品牌。当前问题分数主要依赖：

```text
coverage × normalized_entropy
```

品牌值多、熵高，因此几乎总是获胜。但问题经常变成：

```text
skdoiul、tsiodfo、dreamcity，你喜欢哪个品牌？
```

这类问题数学上可以切分候选，真实用户却很难回答，也不一定符合购物决策顺序。

### 问题 7：问询属性耗尽后进入死循环

多个失败会话出现相同轨迹：

```text
brand
→ color/material
→ style/use_case
→ budget
→ ask_attribute = null
→ 用户表示结果不合适并要求继续问
→ Agent 继续返回同一批或高度相似的推荐
→ 一直停滞到第 10 轮
```

`public_0028`、`public_0033`、`public_0035`、`public_0046` 和 `public_0198` 都能看到这一模式。

根因是系统没有明确的 `reject_results` 行为，问询策略只遍历固定属性集合，也没有检测连续推荐是否停滞。

### 问题 8：`no_preference` 没有完整作用于下游

用户回答“品牌无所谓”后，系统通常不会再次询问品牌，但这个信息主要只影响问询去重，没有完整影响：

- 旧软约束清理。
- Profile 偏好使用。
- 排序特征。
- 新问题选择。

Boundary 场景 HitRate 为 `0.9`，MRR 却只有 `0.250397`，说明目标经常能进入 Top 10，但没有被有效排到前部。

### 问题 9：脏商品字段会导致整轮失败

`public_0197` 中某个商品价格为字符串：

```text
—
```

排序阶段转换数值时抛出异常，前三轮没有正常生成回复。基础价格保护已经在本轮跑完后修复并加入回归测试，但其他字段仍应按相同原则检查。

### 问题 10：Trace 尚不能完整定位排名损失

当前节点 Trace 为控制文件大小，只保留每个候选阶段 Top 20。我们只能知道目标是否进入 Top 20，却不知道：

- 目标是第 21 名还是第 400 名。
- 目标是否存在于完整候选集中。
- 目标被哪一条过滤规则删除。
- 目标在 Fusion 和 Reranker 之间下降了多少名。

因此目前的失败分类仍需要大量人工检查。

## 三、问题与五个大板块的对应关系

| 编号 | 本轮发现的问题 | 主负责板块 | 协作板块 |
|---:|---|---|---|
| 1 | 控制语句、单位、重复和冲突约束误解析 | 语义理解与状态 | 评测与集成 |
| 2 | 硬约束不能有效缩小候选 | 检索、过滤与融合 | 语义理解 |
| 3 | Dense 语义召回弱 | 检索、过滤与融合 | 评测 |
| 4 | 属性召回目标被 RRF 淹没 | 检索、过滤与融合 | 精排 |
| 5 | 融合高排名目标被精排排掉 | 精排 | 检索 |
| 6 | 199/200 首轮询问品牌 | 问询与回复 | 评测 |
| 7 | 问询耗尽后重复推荐 | 问询与回复 | 语义理解、编排 |
| 8 | `no_preference` 没有完整作用于下游 | 语义理解与状态 | 问询、精排 |
| 9 | 脏商品字段导致运行错误 | 数据可靠性与集成 | 精排、检索 |
| 10 | Trace 无法完整定位目标排名损失 | Trace、评测与集成 | 所有板块 |

## 四、板块一：语义理解与用户诉求状态

### 对应之前的问题

- 问题 1：控制语句、单位、重复约束和冲突约束误解析。
- 问题 8：`no_preference` 没有完整清除偏好。
- 问题 7 的上游部分：系统不能识别用户正在拒绝当前结果。

### 负责代码

```text
src/shopping_agent/understanding/
├─ interpreter.py
├─ prompts.py
├─ state_patch.py
└─ fallback_parser.py

src/shopping_agent/domain/
├─ schemas.py
├─ state.py
└─ intent.py
```

### 需要完成的修改

#### 1. 增加对话行为分类

建议给 `StatePatch` 增加：

```python
conversation_act: Literal[
    "constraint_update",
    "reject_results",
    "request_clarification",
    "no_preference",
    "intent_override",
    "general_reply",
]
```

只有 `constraint_update` 和 `intent_override` 可以新增商品约束。

#### 2. 增加单位与上下文联合判断

最低规则：

```text
30mm / 30 cm / 12 inch → size
$30 / 30 dollars       → budget
under 30               → 根据上下文判断；低置信度时不产生硬约束
```

#### 3. 做语义级约束规范化

- 去掉 `color:`、`material:` 等字段前缀。
- 大小写与空格归一化。
- 建立常见颜色、材质、类别别名。
- 同字段同义值合并。
- 正负约束冲突处理。
- 新预算替换旧预算。

#### 4. 完善多轮状态

- `reject_results` 增加拒绝计数，但不能污染商品约束。
- `no_preference` 清除对应字段的旧软约束。
- `intent_override` 退休不再适用的旧约束。
- `semantic_query` 每轮都表达当前完整有效诉求。

### 交付物

- 新版 `StatePatch`。
- 对话行为分类 Prompt。
- 单位和字段解析逻辑。
- 约束规范化与冲突处理。
- 理解层单元测试和多轮回归测试。

### 验收标准

- `public_0197` 的 `30mm` 不再成为预算。
- “结果不合适，请继续问”不再生成商品约束。
- `color: black` 和 `black` 只保留一个规范约束。
- 同字段不会保留互相冲突的正负约束。
- 用户明确无偏好后，相应旧软约束被清除。
- LLM 失败时本地 Parser 仍能生成合法 Patch。

### 建议分支

```text
feature/intent-state-v2
```

## 五、板块二：检索、结构化粗筛与候选融合

### 对应之前的问题

- 问题 2：硬约束无法有效缩小候选。
- 问题 3：Dense 语义召回弱。
- 问题 4：属性召回目标在 RRF 中丢失。

### 负责代码

```text
src/shopping_agent/retrieval/
├─ interfaces.py
├─ lexical.py
├─ semantic.py
├─ attributes.py
└─ fusion.py

src/shopping_agent/infrastructure/vector_store/
```

### 需要完成的修改

#### 1. 实现三态约束匹配

统一输出：

```text
MATCH
UNKNOWN
CONTRADICT
```

执行规则：

```text
MATCH       → 保留并加分
UNKNOWN     → 保留，但降低可信度
CONTRADICT  → 硬约束直接过滤
```

优先覆盖 category、material、color、budget、size、brand 和 feature。

#### 2. 建立类别层级匹配

- 将长类别路径拆成层级 Token。
- 区分子类别一致、同大类和完全不相关。
- 不再要求完整类别字符串原样出现。
- 为下游 Reranker 输出 `category_match_level`。

#### 3. 接入真实语义检索

- 保留 `LocalDenseIndex` 作为可靠兜底。
- 实现新的 `SemanticRetriever`。
- 使用真实 Embedding 和向量数据库。
- 设计标题、类别、属性、功能和描述的向量文本结构。
- 记录 Embedding 模型与索引版本。
- 远程失败时自动降级。

#### 4. 重构融合

- 不同 Route 使用可配置权重。
- 每路 Top N 候选保底。
- 属性强命中保护。
- 使用 `route_count`。
- 加入类别一致性和硬约束命中数。
- 输出可解释 Fusion 字段。

### 交付物

- 统一 `ConstraintMatcher`。
- 类别层级匹配工具。
- 真实向量检索适配器。
- 加权 RRF 或新 Fusion 实现。
- 各通道 Recall@20/100 报告。

### 验收标准

- 明确材质和颜色能够合理缩小候选集。
- 明确不相关类别不再大量进入过滤结果。
- Attribute Top 10 强命中不会轻易跌出 Fusion Top 100。
- Dense 在困难失败集上的 Recall@20 明显高于当前 `1/20`。
- 向量库不可用时能自动退回本地语义检索。

### 建议分支

```text
feature/retrieval-fusion-v2
```

## 六、板块三：精排与最终推荐排序

### 对应之前的问题

- 问题 5：融合前部的目标被 Reranker 排掉。
- 问题 8 的下游部分：无偏好字段仍可能影响排序。
- 问题 9 的部分责任：排序必须容忍脏候选字段。

### 负责代码

```text
src/shopping_agent/ranking/
├─ interfaces.py
└─ fallback.py
```

### 需要完成的修改

#### 1. 拆分可解释评分

建议分别计算：

```text
category_score
hard_constraint_score
soft_preference_score
semantic_score
lexical_score
fusion_score
profile_score
quality_score
contradiction_penalty
novelty_penalty
```

#### 2. 强化类别相关性

- 子类别一致：高分。
- 同一大类：中等分。
- 完全不相关：强惩罚。
- 上游漏过的明确类别冲突由 Reranker 做最后保护。

#### 3. 正确处理约束操作符

分别实现：

```text
contains
not_contains
eq
lte
gte
```

负向约束不能按照普通词面命中得到正分。

#### 4. 限制质量特征

评论数量和平均评分只用于相关商品之间的次级排序，不能让类别错误的热门商品超过需求高度匹配商品。

#### 5. 为模型精排保留接口

先修复本地可解释 Reranker，再比较 Cross Encoder、Learning to Rank 或 LLM Reranker。模型升级不能掩盖基础规则错误。

### 交付物

- 新版可解释 Fallback Reranker。
- 每个候选的分项得分。
- Rerank 前后目标排名报告。
- 可选模型精排实验报告。

### 验收标准

- `public_0046` 中 Fusion Rank 1 的目标不能再被排出 Top 10。
- 类别不相关商品不能仅凭相同材质占据前排。
- 商品质量特征不能压过核心相关性。
- `not_contains` 和预算上下限评分正确。
- MRR 提升时 HitRate 不出现明显下降。

### 建议分支

```text
feature/reranking-v2
```

## 七、板块四：问询策略与对话回复

### 对应之前的问题

- 问题 6：199/200 首轮询问品牌。
- 问题 7：问题耗尽后重复推荐。
- 问题 8 的对话部分：无偏好后没有选出新的有效问题。

### 负责代码

```text
src/shopping_agent/dialogue/
├─ question_policy.py
└─ response_builder.py
```

### 需要完成的修改

#### 1. 重构问题效用

从当前主要依赖信息熵，改成：

```text
Question Utility
= Expected Candidate Reduction
 × User Answerability
 × Business Relevance
 - High Cardinality Penalty
 - Obscure Value Penalty
 - Repeated Question Penalty
```

#### 2. 降低品牌优先级

建议默认优先级：

1. 商品类型或形态。
2. 使用场景。
3. 功能。
4. 材质。
5. 尺码。
6. 风格。
7. 预算。
8. 颜色。
9. 品牌。

品牌只在用户主动提及，或候选由少量可识别品牌构成时优先。

#### 3. 增加用户拒绝策略

当：

```text
conversation_act == reject_results
```

可以：

- 询问尚未覆盖的功能属性。
- 询问子类别或商品形态。
- 询问用户最不能接受什么。
- 放宽一个软约束。
- 给出两组不同方向让用户选择。

#### 4. 检测推荐停滞

建议在状态中增加：

```text
rejection_count
recommendation_stagnation_count
last_question_attribute
question_strategy
```

连续两轮推荐高度相似时，必须切换问题或检索策略。

### 交付物

- 新版问题效用函数。
- `reject_results` 对话策略。
- 推荐停滞检测。
- 中英文问题生成策略。
- 问询行为回归测试。

### 验收标准

- 第一轮询问品牌比例显著低于 `199/200`。
- 不询问用户已回答或明确无偏好的字段。
- 用户拒绝结果后不再原样重复推荐。
- `ask_attribute=null` 后不会一直停滞到第 10 轮。
- 问题和选项是普通用户可以理解并回答的。

### 建议分支

```text
feature/dialogue-policy-v2
```

## 八、板块五：数据可靠性、Trace、评测与主链路集成

### 对应之前的问题

- 问题 9：脏价格导致整个排序节点失败。
- 问题 10：Trace 无法完整定位目标在哪一阶段丢失。
- 为其他四个板块提供统一集成和验收。

### 负责代码

```text
src/shopping_agent/observability/
├─ tracing.py

src/shopping_agent/orchestration/
├─ graph.py
├─ nodes.py
└─ routing.py

src/shopping_agent/domain/product_text.py
scripts/
tests/
```

### 需要完成的修改

#### 1. 数据字段鲁棒性

统一处理：

```text
None
""
"—"
"$19.99"
"19–29"
"30mm"
```

单个商品字段异常不能终止整个候选列表或用户轮次。

#### 2. 保存完整目标阶段排名

离线评测额外计算：

```text
target_lexical_rank
target_dense_rank
target_attribute_rank
target_fusion_rank
target_filtered_rank
target_reranked_rank
target_filtered_reason
```

这些目标标签只能出现在评测和 Trace 中，不能进入真实产品 Agent 的决策状态。

#### 3. 自动失败分类

新增 `scripts/analyze_failure_cases.py`，把失败分类为：

```text
UNDERSTANDING_FAILURE
RECALL_FAILURE
FILTER_FAILURE
FUSION_FAILURE
RANKING_FAILURE
DIALOGUE_STALL
RUNTIME_ERROR
```

#### 4. 统一 Graph 集成

其他功能组尽量不直接修改 Graph，由集成人负责：

- 接入 `conversation_act`。
- 注入新的 Retriever 和 Ranker。
- 增加拒绝结果路由。
- 合并新状态字段。
- 保持节点名称和 Trace 兼容。
- 运行测试和完整评测。

### 交付物

- `scripts/analyze_failure_cases.py`。
- 新版 Trace Schema。
- 自动失败分类报告。
- 集成后的 LangGraph。
- 完整 200 条回归结果。

### 验收标准

- 每个未命中案例能自动识别主要失败阶段。
- 可以比较改动前后每个样本在各节点的排名变化。
- 脏商品字段不再造成整轮失败。
- 本地兜底、LLM 和 Trace 三种运行方式都能执行。
- 全部测试通过。
- 产品代码不存在目标标签泄漏。

### 建议分支

```text
feature/evaluation-observability-v2
```

## 九、团队分工建议

### 5 人配置

| 人员 | 负责板块 |
|---|---|
| 组员 A | 语义理解与用户诉求状态 |
| 组员 B | 检索、结构化粗筛与候选融合 |
| 组员 C | 精排与最终推荐排序 |
| 组员 D | 问询策略与对话回复 |
| 组员 E / 项目负责人 | 数据可靠性、Trace、评测与主链路集成 |

### 4 人配置

| 人员 | 负责板块 |
|---|---|
| 组员 A | 语义理解与状态 |
| 组员 B | 检索、过滤与融合 |
| 组员 C | 精排 |
| 组员 D / 项目负责人 | 问询、评测和 Graph 集成 |

### 3 人配置

| 人员 | 负责板块 |
|---|---|
| 组员 A | 语义理解、状态和问询 |
| 组员 B | 检索、过滤和融合 |
| 组员 C / 项目负责人 | 精排、评测和 Graph 集成 |

## 十、并行开发前必须冻结的接口

### 1. `StatePatch`

确认是否增加：

```text
conversation_act
```

并明确哪些行为允许修改商品约束。

### 2. 约束匹配结果

统一使用：

```text
MATCH / UNKNOWN / CONTRADICT
```

避免过滤模块和排序模块对同一约束产生不同解释。

### 3. 候选字段

至少保留：

```text
parent_asin
lexical_rank / lexical_score
dense_rank / dense_score
attribute_rank / attribute_score
rrf_score
route_count
constraint_match_summary
category_match_level
reranker_score
```

### 4. Trace 字段

统一阶段目标排名、过滤原因和错误分类字段，避免不同分支生成不兼容的评测产物。

这四项契约应先以一个小 PR 合入集成分支，然后各组员并行开发。

## 十一、推荐分支结构

总集成分支：

```text
improve/agent-v2
```

功能分支：

```text
feature/intent-state-v2
feature/retrieval-fusion-v2
feature/reranking-v2
feature/dialogue-policy-v2
feature/evaluation-observability-v2
```

合并路径：

```text
功能分支
    ↓
improve/agent-v2
    ↓
单元测试、行为回归、小样本 Trace
    ↓
200 条完整评测
    ↓
main
```

推荐通过 Worktree 同时浏览不同分支：

```powershell
git worktree add -b improve/agent-v2 ..\techjam-agent-v2 main
```

## 十二、实施优先级

### P0：确定性错误和主链路可靠性

1. 对话控制语句不能生成商品约束。
2. `30mm` 等尺寸不能被识别成预算。
3. 重复和冲突约束必须清理。
4. 类别不相关商品不能大量进入最终排序。
5. Fusion 高排名目标不能被基础 Reranker 无理由排掉。
6. 脏字段不能导致整轮失败。

### P1：直接影响分数和真实用户体验

1. 重构问题效用，解决首轮几乎总问品牌。
2. 完成三态约束过滤。
3. 调整 Fusion，保护属性强命中。
4. 解决用户拒绝后的对话停滞。
5. 增强 Trace 和自动失败分类。

### P2：模型能力升级

1. 接入真实 Embedding 和向量数据库。
2. 接入 Cross Encoder 或学习排序。
3. 建立独立的召回、排序和问询评测集。

## 十三、推荐实验顺序

不要一次性合入全部改动后只跑一个总分。建议每一步保存独立 Trace：

### 实验 1：理解与状态修复

观察：

- 错误约束率。
- 重复约束率。
- Intent Override 正确率。
- Reject/No Preference 行为正确率。

### 实验 2：类别和三态过滤

观察：

- 候选数量变化。
- 目标误过滤率。
- 明确冲突商品保留率。
- Filter 前后 Recall。

### 实验 3：Fusion 和 Fallback Reranker

观察：

- Attribute Top 20 到 Fusion Top 20 的保留率。
- Fusion 到 Rerank 的目标排名变化。
- HitRate 与 MRR。

### 实验 4：问询策略

观察：

- 首轮品牌问题比例。
- 问题重复率。
- 回答后的候选缩减。
- 推荐停滞率。
- MTTC。

### 实验 5：真实向量检索

观察：

- Dense Recall@20/100。
- 5 个纯召回困难案例是否改善。
- 总体 HitRate、MRR、延迟和成本。

## 十四、重点回归案例

| Sample | 主要用途 |
|---|---|
| `public_0028` | 重复颜色约束、硬约束粗筛、问询耗尽和推荐停滞 |
| `public_0033` | Attribute 找到目标但最终长期停留在 Top 10 外 |
| `public_0035` | Boundary/no-preference 和对话停滞 |
| `public_0046` | Fusion Rank 1 被精排排掉，类别相关性错误 |
| `public_0197` | `30mm` 误识别、脏价格异常和 Intent Override |
| `public_0198` | Intent Override、重复颜色约束和拒绝后停滞 |
| `public_0029` | 纯召回困难案例 |
| `public_0074` | 纯召回困难案例 |
| `public_0096` | 纯召回困难案例 |
| `public_0161` | 纯召回困难案例 |
| `public_0167` | 纯召回困难案例 |

这些案例只用于验证通用能力。产品代码和 Prompt 中禁止出现 Sample ID、目标 ASIN 或针对目标商品的特殊规则。

## 十五、每个功能分支的统一交付要求

每个模块负责人提交时至少提供：

1. 模块代码。
2. 单元测试或行为回归测试。
3. 修改前后的代表性 Trace。
4. 至少一个成功案例和一个失败案例分析。
5. 指标变化。
6. 延迟或成本变化。
7. 已知风险和回滚方式。

不能只提供“公开集总分提高了”这一项结果。

## 十六、下一轮完成标准

下一轮至少同时满足：

- 理解层不再把对话控制语句当成商品约束。
- 数字和单位字段误判显著减少。
- 结构化信息能够有效缩小候选，但不会大规模误删目标。
- Attribute 强命中在 Fusion 中得到保护。
- `public_0046` 类型的精排灾难被修复。
- 第一轮品牌问题比例明显下降。
- 用户拒绝结果后不会连续重复相同推荐。
- 脏商品字段测试全部通过。
- 每个失败案例可以自动定位主要失败阶段。
- 完整评测保存 HitRate、MRR、MTTC、token、延迟和配置。

## 十七、任务拆分结论

五个板块分别回答五个不同问题：

```text
语义理解与状态
→ 用户需求有没有理解对、状态有没有维护对？

检索、过滤与融合
→ 正确商品有没有进入高质量候选集？

精排
→ 正确商品已经找到后，能不能进入最终 Top 10？

问询与回复
→ 信息不足或用户不满意时，Agent 下一步应该做什么？

数据可靠性、Trace 与集成
→ 系统是否稳定，我们能否准确知道问题发生在哪里？
```

五个板块通过显式 Schema 和 Protocol 连接，可以并行开发。项目负责人应重点维护公共状态、Graph、Trace 和最终评测，避免各组直接在主链路中加入互相冲突的特殊逻辑。
