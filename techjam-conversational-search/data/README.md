# 数据格式

[项目说明](../../README.md)

默认评测入口读取：

```text
data/catalog.jsonl      商品目录
data/test/users.jsonl   用户测试集
```

两者均为 UTF-8、无 BOM 的 JSONL，每行一个 JSON 对象。catalog 不留空行；`.gz` 文件先解压。`data/test/` 不提交到 Git。

## 商品目录

商品以 `parent_asin` 为唯一主键。保留标题、属性、描述和评分等原始字段供召回与排序使用：

```json
{"parent_asin":"DEMO_SHOE_001","title":"Blue waterproof shoes","features":["Waterproof","Lightweight"],"description":["Walking shoes"],"categories":["Clothing","Shoes"],"details":{"Color":"Blue","Size":"M"},"price":59.0,"average_rating":4.4,"rating_number":50,"store":"Demo"}
```

`features`、`description`、`categories` 为字符串数组，`details` 为对象，`price` 和评分字段为数值或 null。测试集引用的目标 ID 必须存在于本次 catalog。

## 用户测试集

与随包 `public_set.jsonl` 保持相同格式：

```json
{"sample_id":"test_001","scenario_type":"buying","user_profile":{"purchase_frequency":"unknown","average_prior_rating":null,"rating_style":"unknown","preference_tags":[],"summary":""},"ground_truth":{"parent_asin":"DEMO_SHOE_001"}}
```

| 字段 | 说明 |
|---|---|
| `sample_id` | 唯一会话 ID |
| `scenario_type` | `buying`、`browsing`、`intent_override` 或 `boundary` |
| `user_profile` | 用户聚合画像对象 |
| `ground_truth.parent_asin` | 目标商品 ID，由评测器用于计分 |

`category_bucket`、`difficulty_bucket` 可作为附加分析字段。缺少 `intent_card` 与 `behavior` 时，随包评测器根据目标商品生成模拟状态；使用自有对话策略的测试框架可直接调用 `Agent.reset/respond`。

仅有用户聊天文本、没有目标 ID 的文件不能直接用于指定商品 Hit@10 评测。Agent 不读取测试标签，仅接收用户画像及逐轮消息。

随包公开集为 200 条，配套商品目录为 50,000 条。完整 catalog 由主办方提供，不随源码提交。数据来源见 [DATA_ATTRIBUTION.md](../DATA_ATTRIBUTION.md)。
