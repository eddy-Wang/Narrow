# Active LambdaMART model bundle

Selected on 2026-09-01: **round3**, evaluated with **deepseek-v4-flash** on the official public 200.
The learner and runtime 13-feature schema are unchanged. This directory contains one complete frozen bundle.

[Comparison and limitations](../../docs/mrr_loss_search_20260901.md) · [All preserved weights](../loss_search_20260901/README.md)

| File | SHA-256 |
|---|---|
| `model.txt` | `ef9edb3aa787e09d725749139cbed68015671195880dfd8d4909195716d96a4c` |
| `idf.json` | `edbad34a30a6747926873b8917b21d0b27f8428a7205ba5347d29ccb7fbde714` |
| `metadata.json` | `250bc54e109508727ef968fee46fdef29993cc9409933e846142abac50f5da9b` |
| `same_data_linear_weights.json` | `a6b5530dd2f65502f2a721a7c686448d100940d0a5fd22060d3beb4f55a244a0` |

Keep model.txt, idf.json and metadata.json together. The linear weights are an audit control, not the active ranking model.
For baseline_r4 they are a historical control from the earlier experiment, not a same-data r4 control.
Training provenance and feature order are recorded in metadata.json. Absolute training-machine paths are provenance only.
Public-test reuse and one-run LLM variation limit the strength of the model comparison; do not present it as an unseen private leaderboard score.
