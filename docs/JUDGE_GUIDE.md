# Judge's guide to the submission folder

Start with the [English README](../README.md). A [Chinese backup](../README.zh-CN.md)
is included. Run `run_evaluation.ps1`; retraining and frontend installation
are not required for command-line evaluation.

## Top-level files and folders

| Path | Purpose | Needed for CLI evaluation? |
|---|---|---|
| `README.md` | English setup and run instructions | Read first |
| `README.zh-CN.md` | Chinese backup | No |
| `run_evaluation.ps1` | Main online evaluation entry; accepts `-Workers` | Yes |
| `run_local_python.ps1` | Finds the project Python environment and runs backend scripts | Yes |
| `techjam-conversational-search/` | Agent, pretrained model, evaluator, and backend | Yes |
| `demo-frontend/` | Interactive shopping workbench | Browser demo only |
| `trace-visualizer/` | Conversation and node trace viewer | Trace inspection only |
| `user-simulator/` | Alternative simulation modes and tests | No, for the main CLI entry |
| `scripts/` | Demo launch and development helpers | As needed |
| `docs/` | Testing instructions, trace specification, and supporting reports | Reference |
| `synthetic_scenarios_2000.jsonl` | Synthetic training source | No; not judge test data |
| `test_results/`, `demo_runs/` | Generated local reports and workbench runs, when present | No |

## Backend files

Paths below are relative to `techjam-conversational-search/`.

| Path | Role |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version` | Requirements and locked dependency versions |
| `.env.example` | Configuration template with no real credential |
| `.env` | Local API key/settings; create locally and never share |
| `submission_agent.py` | Evaluator-compatible `Agent` import |
| `src/shopping_agent/application/` | Session lifecycle and public methods |
| `src/shopping_agent/understanding/` | User requirement extraction and updates |
| `src/shopping_agent/retrieval/` | Candidate retrieval and filtering |
| `src/shopping_agent/ranking/` | The 13 features and frozen LambdaMART scoring |
| `src/shopping_agent/dialogue/` | Follow-up questions and recommendation responses |
| `src/shopping_agent/orchestration/` | Agent execution stages |
| `evaluator/` | Test protocol, simulated user turns, target matching, and metrics |
| `scripts/evaluate_parallel_with_traces.py` | Online evaluation with isolated workers |
| `scripts/evaluate_with_traces.py` | Single-worker evaluation and raw traces |
| `scripts/experiment_lambdamart.py` | Optional offline training; not used in inference |
| `scripts/mrr_objective.py` | Experimental loss functions; not imported by runtime ranking |
| `tests/` | Unit, integration, and regression checks |
| `DATA_ATTRIBUTION.md` | Data attribution and usage context |

## Data and weights

| Path | Explanation |
|---|---|
| `data/catalog.jsonl` | Organizer-provided product catalog; large local file ignored by Git |
| `data/test/users.jsonl` | Current evaluation scenarios; may be replaced with a compatible judge set |
| `data/public_set.jsonl` | Included public 200-scenario set; not an unseen private holdout |
| `data/synthetic_scenarios_2000.jsonl` | Synthetic training source from the 50,000-product catalog |
| `models/lambdamart_synthetic_2000/model.txt` | Active pretrained LightGBM tree ensemble |
| `models/lambdamart_synthetic_2000/idf.json` | Frozen term weights used by feature extraction |
| `models/lambdamart_synthetic_2000/metadata.json` | Schema, training parameters, split, and provenance |
| `models/lambdamart_synthetic_2000/same_data_linear_weights.json` | Linear audit comparison weights; not the active reranker |
| `models/lambdamart_synthetic_2000/README.md` | Authoritative active-bundle description |
| `models/loss_search_20260901/` | Original weights, NDCG control, and all three loss variants |
| `models/loss_search_20260901/manifest.json` | File hashes, fixed training settings, and comparison rule |
| `models/loss_search_20260901/selection.json` | Verified Flash metrics, chosen bundle, and comparison limitations |

The active bundle is round 3, selected for the highest observed MRR while
maintaining Hit@10 above the original Flash baseline. Round 1 has the higher
Hit@10 and composite technical score and remains available in the archive.
See the [complete comparison](../techjam-conversational-search/docs/mrr_loss_search_20260901.md).

Keep `model.txt`, `idf.json`, and `metadata.json` from the same bundle
together. The folder name alone does not identify training provenance.
Feature schema and order are checked at load time.

The loss experiments exclude 418 synthetic scenarios whose targets also
appear in the official public set, leaving 1291 training and 291 validation
scenarios. The candidate catalog still contains every product. The public
200 never supplies training gradients, but is reused to compare weights at
the user's request. Its scores are development evidence, not unbiased
estimates on unseen data. The original deployed weights were trained in a
different experiment; comparisons among the three new rounds isolate loss
changes more closely than comparison with the original bundle.

## Reading an evaluation run

Open `evaluation_runs/test/LATEST.txt`, then the directory it identifies.
Loss experiments use `evaluation_runs/loss_flash_20260901/<variant>/`.

| File | What to inspect |
|---|---|
| `report.md` | Human-readable metric summary |
| `summary.json` | Full metrics and failed-turn count |
| `run_config.json` | Model hash, LLM name, data paths, and worker settings |
| `sessions.jsonl` | One result per evaluated scenario |
| `turns.jsonl` | User messages, agent responses, target ranks, and errors |
| `trace.json` | Import into the trace viewer |
| `node_traces.jsonl` | Intermediate intent and candidate state |
| `llm_calls.jsonl` | API requests/responses, excluding authentication |
| `rank_calls.jsonl` | Candidate features, scores, and ranking diagnostics |
| `shards/` | Worker datasets, logs, and raw output |

Hit@10 counts a scenario as successful when its specified target enters the
first ten allowed recommendations. MRR averages reciprocal target rank at
the first successful turn; failures contribute zero. MTTC uses the first
successful turn, assigning eleven to an unsuccessful ten-turn session.
Intent-override scenarios cannot succeed before the scheduled change.
These are simulator metrics, not purchase conversion or general relevance.

Check both `sample_count` and `failed_turn_count`. Zero failed turns means
no recorded execution errors, not that every target was retrieved. API calls
incur charges. Traces contain test content; do not publish private judge
inputs, credentials, or local environment files.
