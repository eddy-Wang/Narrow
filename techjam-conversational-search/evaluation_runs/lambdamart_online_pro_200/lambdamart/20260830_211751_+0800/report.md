# Parallel Traced Evaluation Report

Run: `20260830_211751_+0800`  
Model: `deepseek-v4-pro`  
Workers: `4`  
Samples: `200`

## Score

| Metric | Value |
|---|---:|
| Hit Rate@10 | 0.970000 |
| MRR | 0.511349 |
| MTTC | 2.295000 |
| Efficiency | 0.870500 |
| Technical Score | 0.812505 |
| Prompt tokens | 994545 |
| Completion tokens | 130642 |
| Total tokens | 1125187 |

## Scenario breakdown

| Scenario | Samples | Hit Rate | MRR | MTTC |
|---|---:|---:|---:|---:|
| boundary | 10 | 1.000000 | 0.428452 | 2.300000 |
| browsing | 80 | 0.975000 | 0.464816 | 2.162500 |
| buying | 80 | 0.962500 | 0.528214 | 1.725000 |
| intent_override | 30 | 0.966667 | 0.618095 | 4.166667 |

Complete aggregate data is stored in `sessions.jsonl`, `turns.jsonl`,
and `node_traces.jsonl`. Per-worker raw outputs and logs are under `shards/`.

## Detailed trace audit

{
  "status": "passed",
  "sessions": 200,
  "turns": 453,
  "node_records": 4959,
  "full_candidate_snapshots": 1750,
  "ranking_records": 451,
  "maximum_candidates_per_rank": 500,
  "sdk_calls": 904,
  "sdk_errors": [],
  "response_models": {
    "deepseek-v4-pro": 904
  },
  "raw_sdk_usage": {
    "prompt_tokens": 1011397,
    "completion_tokens": 133779,
    "total_tokens": 1145176
  },
  "reported_agent_usage": {
    "prompt_tokens": 994545,
    "completion_tokens": 130642,
    "total_tokens": 1125187
  },
  "turn_errors": [
    {
      "sample_id": "public_0010",
      "turn": 1,
      "error": "RuntimeError: Online dialogue failed (DeepSeekInvalidResponse); offline fallback is disabled"
    },
    {
      "sample_id": "public_0022",
      "turn": 1,
      "error": "RuntimeError: Online dialogue failed (DeepSeekInvalidResponse); offline fallback is disabled"
    },
    {
      "sample_id": "public_0029",
      "turn": 4,
      "error": "RuntimeError: Online dialogue failed (ValidationError); offline fallback is disabled"
    },
    {
      "sample_id": "public_0044",
      "turn": 1,
      "error": "RuntimeError: Online dialogue failed (DeepSeekInvalidResponse); offline fallback is disabled"
    },
    {
      "sample_id": "public_0054",
      "turn": 1,
      "error": "RuntimeError: Online dialogue failed (DeepSeekInvalidResponse); offline fallback is disabled"
    },
    {
      "sample_id": "public_0109",
      "turn": 1,
      "error": "RuntimeError: Online dialogue failed (DeepSeekInvalidResponse); offline fallback is disabled"
    },
    {
      "sample_id": "public_0129",
      "turn": 1,
      "error": "RuntimeError: Online dialogue failed (DeepSeekInvalidResponse); offline fallback is disabled"
    },
    {
      "sample_id": "public_0166",
      "turn": 4,
      "error": "RuntimeError: Online intent failed (DeepSeekInvalidResponse); offline fallback is disabled"
    },
    {
      "sample_id": "public_0197",
      "turn": 4,
      "error": "RuntimeError: Online intent failed (DeepSeekInvalidResponse); offline fallback is disabled"
    }
  ],
  "rank_latency_ms": {
    "median": 12.306399876251817,
    "p95": 22.555749979801476
  },
  "note": "Full original candidate snapshots and scores are local JSONL; SDK-internal HTTP retries are not separate events.",
  "frozen_model_sha256": "d4243775f26f8fc5b651becd0100d6a69d232401b73b7371f1c9e0bc4f72b79a"
}

Full local records: sessions.jsonl, turns.jsonl, node_traces.jsonl, llm_calls.jsonl, rank_calls.jsonl. trace.json is the existing viewer summary; full LLM requests and candidate features remain in JSONL. The LLM interprets intent and chooses dialogue actions online; simulated users remain local. The offline-trained tree was not retrained or tuned on this test. Only LambdaMART Pro was requested; cancelled duplicate baseline and Flash runs are excluded.
