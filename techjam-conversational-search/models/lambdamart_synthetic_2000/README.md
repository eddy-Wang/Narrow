# Active LambdaMART model bundle

Replaced on 2026-09-01 with the [r4 model from the requested experiment](https://github.com/zhouziyueharry-droid/tiktok_project_4/tree/335bb23cc34605d19744de9877101c8ade2c17d4/techjam-conversational-search/experiments/lambdamart_2k_new100k_integrated_deepseekv4pro_20260831_r4/model).
Source branch: `experiment/final-rawmetadata500k-2k-20260831`.

`model.txt`, `idf.json`, and `metadata.json` are copied byte-for-byte from that source. Keep all three together. The existing directory name is retained so CLI and demo loading paths do not change.

The model has 66 trees and the same 13-feature schema (version 1). Its metadata records 1621 training and 379 validation sessions, with offline training on the new 100k-product catalog. Absolute paths in metadata describe the training machine; runtime loading does not use them.

SHA-256:

| File | Hash |
|---|---|
| `model.txt` | `e701253a8d8635d164ea29fc2fdd173033da76791aede5160e8a9dee899c6ad5` |
| `idf.json` | `f8521f96ebf865c5c2ee8dde9ca950c015074917b624ee83dd744520b4a9fced` |
| `metadata.json` | `fe9b42fbbb91c9e24f58adc106812a64b2b4368d10fd7f82502fe9ddb69e8af4` |

`same_data_linear_weights.json` is unchanged: it belongs to the previous experiment and is still required by the existing audit logger. It is a historical linear baseline, not a linear model trained on this r4 model's data.

Only the LambdaMART bundle changed. Precise and the existing ranker selection defaults are unchanged; select LambdaMART to use these weights. Install the `ltr` extra before loading the bundle.

Historical [evaluation](../../docs/lambdamart_online_pro_report.md) and [training](../../docs/lambdamart_training.md) reports describe the previous model, not a new evaluation of this bundle. Previous weights remain available in Git history.
