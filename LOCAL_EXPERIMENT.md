# LambdaMART 精排实验工作区

- 分支：`codex/lambdamart-reranker`，基于 `main@7f729a2`。本次只推送实验分支，不合并 main。
- 本目录是独立 Git worktree；原项目目录仍在 main。
- Python 环境位于本目录的 `techjam-conversational-search/.venv`，不再借用主项目环境。
- catalog.jsonl 和私有 .env 是本地副本，保持 gitignore。实验脚本不加载 .env，并明确关闭 LLM 和远程追踪。
- 默认仍为 PreciseReranker。LambdaMART 通过已有 reranker 参数注入，不修改业务图、召回、粗排或默认配置。

## 数据与训练

读取根目录用户提供的 synthetic_scenarios_2000.jsonl：2000 条场景、571 个目标商品。
其中 418 条场景的目标覆盖了官方测试的 111 个商品，故排除这 418 条。
剩余场景按目标商品划分，种子 20260830：

| 集合 | 场景 | 独立目标商品 |
|---|---:|---:|
| 训练 | 1291 | 368 |
| 验证 | 291 | 92 |
| 官方测试 | 200 | 200 |

同一目标商品的不同场景不会跨训练、验证、测试集。测试集保留全部场景及其原始比例。
商品目录中的全部 50000 件商品仍可作为检索候选；排除的是监督样本中的目标，并非删掉测试商品。

场景由现有本地模拟器展开为完整对话。每轮真实候选列表是一个排序 group，输入复用原来的13个特征，
包括需求匹配、粗排/召回得分、商品质量、约束冲突、历史推荐等；目标ID只生成标签，不输入排序模型。
目标在候选中标1，其余标0。这是“找指定商品”的弱监督，不等同于真实相关性分级。
训练只用包含目标且有竞争候选的列表，不人为补入未召回目标；意图切换前不使用切换后的目标监督。
每个会话按有效轮次数倒数加权，减轻长会话重复样本的影响。验证集早停选轮数，不使用官方测试调参。

同时训练一个使用完全相同训练特征、标签、样本权重的线性对照。
现有 Precise 的旧权重使用过完整2000条合成数据，具有不同训练量且存在目标商品重合，需区别解读。
树模型的隔离仅针对新训练数据；候选采集仍沿用旧 Precise 的对话轨迹，所以不声称整个系统从未接触过相关目标。
仅进行离线实验，不代表开启在线需求解析后的效果或官方私有榜单成绩。

## 复现

在本工作区根目录运行：

```powershell
uv sync --extra ltr --extra deepseek --group dev --project techjam-conversational-search --cache-dir techjam-conversational-search/.uv-cache
.\run_local_python.ps1 -m pytest tests -q -p no:cacheprovider --basetemp .pytest-run-ltr-check
.\run_local_python.ps1 scripts/experiment_lambdamart.py --synthetic data/synthetic_scenarios_2000.jsonl --output evaluation_runs/lambdamart_synthetic_2000_official_200
```

复现命令使用仓库内已有的合成数据，其解析后的2000条记录与本次使用的根目录文件完全一致；根目录副本不重复提交。克隆后需自行准备被忽略的 data/catalog.jsonl。

output 必须是尚不存在的新目录，避免覆盖已完成实验。
完整模型、数据划分清单、训练特征、候选ID、会话结果和报告均在该输出目录，已忽略大体积实验产物。
模型文件 model.txt 必须与 metadata.json、idf.json 放在同一 model 目录，加载时校验特征顺序和版本。
报告包含完整对话评测，以及冻结同一候选/同一状态的纯排序对照，避免把不同对话轨迹混为模型打分差异。

## 显式接入实验模型

训练好的 model.txt、metadata.json、idf.json 已纳入 models/lambdamart_synthetic_2000/；克隆后无需重新训练，安装依赖并准备商品目录即可使用。大型训练矩阵和评测缓存仍不提交。

从 techjam-conversational-search 目录，用本地环境运行：

```python
from shopping_agent.application.service import ShoppingAgent
from shopping_agent.ranking.lambdamart import LambdaMARTReranker

ranker = LambdaMARTReranker(
    "models/lambdamart_synthetic_2000"
)
agent = ShoppingAgent("data/catalog.jsonl", reranker=ranker)
```

不传 reranker 时，系统继续使用原 PreciseReranker。
模型评分是排序分数，不是购买概率；上游粗排信号作为特征由树学习使用方式，不再直接套用旧线性权重。

## 本次已完成结果

官方200条离线测试：原 Precise / 同数据线性 / LambdaMART 的会话 Hit@10 为87.5% / 91.0% / 92.0%，
MRR 为0.4119 / 0.4388 / 0.4781，平均命中轮数（失败记11）为3.695 / 3.430 / 2.875。
TechnicalScore 为0.7072 / 0.7381 / 0.7659。
LambdaMART 对同数据线性的配对分数差为+0.02789，95%自助法区间[0.00559, 0.05173]。
中位精排耗时分别为16.45 / 16.40 / 18.13毫秒，仅计rank调用；完整对话wall时间不作公平延迟对比。
验证早停选择167棵树；没有基于官方测试重新调参。
可读报告：techjam-conversational-search/docs/lambdamart_experiment_report.md。

附加分析可重复运行，不改变模型：
```powershell
.\run_local_python.ps1 scripts/summarize_lambdamart.py evaluation_runs/lambdamart_synthetic_2000_official_200
```

## 在线 Pro 评测入口

直接复用 scripts/evaluate_parallel_with_traces.py，不使用额外在线总入口。
显式指定 --model deepseek-v4-pro，避免环境配置改变模型。
本次按用户要求只运行新的 lambdamart，不重复运行已有原精排，也不启动线性对照。
原有评测、模拟器和评分规则保持不变。

```powershell
.\run_local_python.ps1 scripts/evaluate_parallel_with_traces.py --model deepseek-v4-pro --workers 4 --candidate-limit 0 --ltr-ranker lambdamart --ltr-model-dir evaluation_runs/lambdamart_synthetic_2000_official_200/model --output-root evaluation_runs/lambdamart_online_pro_200/lambdamart
```

模型继续使用离线训练的已冻结版本。LLM负责在线需求解析和对话决策，模拟用户仍沿用现有本地模拟器。
除了既有 sessions/turns/node_traces/trace.json，额外保存 llm_calls.jsonl 和 rank_calls.jsonl；后者包含全部候选的13个特征、真实排序和三种打分。
LLM请求不含评测隐藏目标标签；日志不保存认证头或密钥。SDK内部HTTP重试不单独展开。
本轮曾误用 Flash，已取消并隔离在 evaluation_runs/lambdamart_online_200/20260830_210858_+0800/CANCELLED.json，不混入 Pro 对照。

用户明确不需要重复基线：重复启动的 Pro precise 已停止，日志保留并标注 CANCELLED.json；本轮交付只包含新的 LambdaMART Pro 官方200条和完整 trace。

本次LambdaMART Pro已完成：200条，Hit@10 97.0%，MRR 0.511349，TechnicalScore 0.812505。详细结果和trace目录见techjam-conversational-search/docs/lambdamart_online_pro_report.md。
