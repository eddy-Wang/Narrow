# Parallel Traced Evaluation Report

Run: `20260829_192723_+0800`  
Model: `deepseek-v4-pro`  
Workers: `4`  
Samples: `200`

## Score

| Metric | Value |
|---|---:|
| Hit Rate@10 | 0.895000 |
| MRR | 0.337327 |
| MTTC | 3.315000 |
| Efficiency | 0.768500 |
| Technical Score | 0.702398 |
| Prompt tokens | 1479989 |
| Completion tokens | 134525 |
| Total tokens | 1614514 |

## Scenario breakdown

| Scenario | Samples | Hit Rate | MRR | MTTC |
|---|---:|---:|---:|---:|
| boundary | 10 | 0.900000 | 0.369286 | 3.800000 |
| browsing | 80 | 0.925000 | 0.335734 | 2.987500 |
| buying | 80 | 0.900000 | 0.330853 | 2.725000 |
| intent_override | 30 | 0.800000 | 0.348188 | 5.600000 |

Complete aggregate data is stored in `sessions.jsonl`, `turns.jsonl`,
and `node_traces.jsonl`. Per-worker raw outputs and logs are under `shards/`.
