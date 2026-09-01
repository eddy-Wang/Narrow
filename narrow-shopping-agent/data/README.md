# Data Format

[Chinese](README.zh-CN.md) · [Project README](../../README.md)

The default evaluation entry reads:

```text
data/catalog.jsonl      Product catalog
data/test/users.jsonl   User scenarios
```

Both files are UTF-8 JSONL without a BOM, with one JSON object per line. The
catalog must not contain blank lines. Decompress `.gz` files first.
`data/test/` is excluded from Git.

## Product catalog

`parent_asin` is the unique product key. Original title, attribute,
description, and rating fields remain available to retrieval and ranking:

```json
{"parent_asin":"DEMO_SHOE_001","title":"Blue waterproof shoes","features":["Waterproof","Lightweight"],"description":["Walking shoes"],"categories":["Clothing","Shoes"],"details":{"Color":"Blue","Size":"M"},"price":59.0,"average_rating":4.4,"rating_number":50,"store":"Demo"}
```

`features`, `description`, and `categories` are arrays of strings. `details`
is an object. `price` and rating fields are numbers or `null`. Every target ID
used by the scenario set must exist in the supplied catalog.

## Scenario set

Use the same format as the included `public_set.jsonl`:

```json
{"sample_id":"test_001","scenario_type":"buying","user_profile":{"purchase_frequency":"unknown","average_prior_rating":null,"rating_style":"unknown","preference_tags":[],"summary":""},"ground_truth":{"parent_asin":"DEMO_SHOE_001"}}
```

| Field | Meaning |
|---|---|
| `sample_id` | Unique session ID |
| `scenario_type` | `buying`, `browsing`, `intent_override`, or `boundary` |
| `user_profile` | Aggregated user-profile object |
| `ground_truth.parent_asin` | Target product ID used only by the evaluator for scoring |

`category_bucket` and `difficulty_bucket` may be included for analysis. When
`intent_card` and `behavior` are absent, the bundled evaluator creates a
simulated state from the target product. A test harness with its own dialogue
policy can call `Agent.reset/respond` directly.

A file containing only chat text and no target ID cannot produce target-specific
Hit@10. The agent never reads evaluation labels; it receives only the user
profile and messages for each turn.

The included public development set has 200 scenarios and its matching catalog
has 50,000 products. The organizer supplies the complete catalog; it is not
committed with the source. See [DATA_ATTRIBUTION.md](../DATA_ATTRIBUTION.md).
