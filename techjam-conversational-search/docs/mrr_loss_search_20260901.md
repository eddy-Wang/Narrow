# Three-round loss comparison with DeepSeek V4 Flash

Selected bundle: **round3**. All four evaluations completed 200 unique official scenarios with zero failed turns.

The comparison was limited to three training rounds that changed only the loss. All rounds used the same LambdaMART architecture, 13 features, catalog, candidate features, IDF values, seed, and fixed hyperparameters. Only the loss's first-place bonus changed (0, 0.5, 1). Early stopping used plain synthetic-validation MRR; tree counts may differ.

The selected 2000-scenario file comes from the 50,000-product catalog. The existing strict target split excludes 418 overlapping sessions, leaving 1291 training and 291 validation sessions. These are 1582 eligible development sessions, not 2000 fitted sessions.

## Official 200, online Flash

| Bundle | Loss first-place bonus | Hit@10 | MRR | Top1 | MTTC | Technical score | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline_r4 | historical NDCG | 96.00% | 0.517125 | 34.50% | 2.530 | 0.804537 | 1,490,995 |
| round1 | 0 | 99.50% | 0.534788 | 34.50% | 1.985 | 0.838236 | 1,159,379 |
| round2 | 0.5 | 99.50% | 0.522169 | 32.50% | 2.025 | 0.833651 | 1,185,736 |
| round3 | 1.0 | 98.50% | 0.543222 | 38.00% | 2.075 | 0.833967 | 1,206,173 |

## Selection and limitations

Among successful full Flash runs with Hit@10 no lower than the baseline Flash run, maximize MRR, then Hit@10, then technical score; include original baseline as candidate. Preserve all weights.

Only the chosen bundle is published under `models/lambdamart_synthetic_2000/`, so the runtime architecture and loading path remain stable. Non-selected checkpoints and raw evaluation runs are development artifacts and are intentionally excluded from Git.

The public 200 was reused to select weights. It is not a pristine holdout. Each bundle has one online run; LLM variability and selection bias limit conclusions. Paired bootstrap intervals below describe these runs and do not correct for selecting the winner. The original r4 also differs in training data, so comparisons against it do not isolate loss alone.

| Candidate vs original Flash | MRR difference | Paired 95% interval |
|---|---:|---|
| round1 | +0.017663 | [-0.037292, +0.072089] |
| round2 | +0.005044 | [-0.048825, +0.060272] |
| round3 | +0.026097 | [-0.027432, +0.079830] |

## Verification

- Recomputed Hit@10, MRR, MTTC and technical score from sessions; checked 200 unique IDs and zero recorded turn errors in each run.
- Verified every archived model, IDF, metadata and linear-control hash against the manifest; verified active files equal the chosen bundle.
- Verified actual captured request and response model names are `deepseek-v4-flash`, not just the run configuration.
- 184 Python checks passed with LLM_MODEL and DEEPSEEK_MODEL explicitly set to deepseek-v4-flash. Two upstream deprecation warnings remain.
- Repository documentation and the judge's file guide are checked against tracked files.

## Artifacts

[Published active bundle](../models/lambdamart_synthetic_2000/README.md) · [Training method](mrr_training.md) · [Judge's guide](../../docs/JUDGE_GUIDE.md)

Earlier Pro results are historical and are excluded from the Flash winner selection.
