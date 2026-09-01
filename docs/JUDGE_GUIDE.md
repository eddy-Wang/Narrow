# Judge's guide to the submission folder

Start with the [English README](../README.md). A [Chinese translation](../README.zh-CN.md)
is included. For command-line evaluation, install the locked Python environment,
provide the catalog and scenarios, configure DeepSeek, and run
`run_evaluation.ps1`. Frontend installation and model retraining are optional.

Every tracked file belongs to one of the groups below. Individual entry points
and frozen artifacts are listed explicitly; implementation and test files are
grouped by responsibility so the map remains useful as files evolve.

## Submission path

| Item | Path | Judge action |
|---|---|---|
| Python interface | `techjam-conversational-search/submission_agent.py` | Import `Agent` |
| Main command | `run_evaluation.ps1` | Run from repository root |
| Python launcher | `run_local_python.ps1` | Used by the main command and documented tests |
| Active model | `techjam-conversational-search/models/lambdamart_synthetic_2000/` | Keep the bundle together |
| Data locations | `techjam-conversational-search/data/catalog.jsonl` and `data/test/users.jsonl` | Supply locally; both are ignored by Git |

The primary path uses DeepSeek V4 Flash for understanding and dialogue, plus
the included LambdaMART model for reranking. It requires network access and a
valid API key. Online failures are recorded as failures rather than silently
replaced with offline output.

## Repository root

| Path | Purpose | CLI scoring? |
|---|---|---|
| `README.md`, `README.zh-CN.md` | Setup, run, results, and documentation index | Read first |
| `.gitignore` | Excludes credentials, local data, generated runs, caches, and builds | Packaging safety |
| `run_evaluation.ps1` | Four-worker online evaluation; accepts `-Workers` | Required |
| `run_local_python.ps1` | Locates the backend environment and runs Python from the correct directory | Required |
| `techjam-conversational-search/` | Agent, model, evaluator, training tools, and tests | Required |
| `demo-frontend/` | Vue shopping workbench | Optional |
| `trace-visualizer/` | Local trace inspection UI | Optional |
| `user-simulator/` | Alternative TechJam and realistic simulation protocols | Optional |
| `scripts/run_demo.ps1`, `scripts/run_demo.sh` | Start the workbench, API, and trace viewer | Optional |
| `docs/` | Judge map, testing instructions, and portable trace schema | Reference |

## Backend map

Paths below are relative to `techjam-conversational-search/`.

| Path | Responsibility |
|---|---|
| `README.md`, `README.zh-CN.md` | Backend overview and documentation index |
| `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore` | Python version, dependency groups, exact lock, and local-output exclusions |
| `.env.example` | Credential-free configuration template; `.env` is never tracked |
| `submission_agent.py` | Evaluator-compatible `Agent` export |
| `langgraph.json`, `src/shopping_agent/studio.py` | Optional LangGraph Studio entry |
| `src/shopping_agent/application/` | Session lifecycle and public application service |
| `src/shopping_agent/domain/` | Intent, product text, schemas, and conversation state |
| `src/shopping_agent/understanding/` | LLM interpretation, deterministic parsing, and state patches |
| `src/shopping_agent/retrieval/` | Lexical, semantic, attribute, fusion, and retrieval policy |
| `src/shopping_agent/ranking/` | Ranker interface, precise baseline, features, and LambdaMART runtime |
| `src/shopping_agent/dialogue/` | Question selection and recommendation response decisions |
| `src/shopping_agent/orchestration/` | LangGraph topology, nodes, and routing |
| `src/shopping_agent/infrastructure/` | DeepSeek and adapter boundaries |
| `src/shopping_agent/observability/` | Trace reconstruction |
| `src/shopping_agent/web.py`, `web_results.py` | Local workbench HTTP API and result adapters |
| Other top-level `src/shopping_agent/*.py` files | Backward-compatible import facades |
| `evaluator/` | Session protocol, target matching, metrics, and trace export |
| `starter/` | Compatibility entry used by the bundled evaluator |
| `scripts/evaluate_parallel_with_traces.py` | Main isolated-worker evaluation implementation |
| `scripts/evaluate_with_traces.py` | Single-worker evaluation and raw trace generation |
| `scripts/experiment_lambdamart.py`, `mrr_objective.py` | Optional offline LambdaMART training |
| Remaining `scripts/*.py` | Synthetic data generation, trace export, smoke checks, or model summaries |
| `tests/unit/`, `tests/integration/`, `tests/regression/` | Isolated logic, component integration, and behavior regression checks |
| `docs/` | Architecture, interfaces, current model training, and selection evidence |
| `DATA_ATTRIBUTION.md` | Data origin and use context |

## Data and model files

| Path | Explanation |
|---|---|
| `data/public_set.jsonl` | Included public 200-scenario development set; not private judge data |
| `data/synthetic_scenarios_2000.jsonl` | Synthetic training scenarios generated from the 50,000-product catalog |
| `data/README.md` | Catalog and scenario JSONL schemas |
| `models/lambdamart_synthetic_2000/model.txt` | Active LightGBM tree ensemble |
| `models/lambdamart_synthetic_2000/idf.json` | Frozen term weights used by feature extraction |
| `models/lambdamart_synthetic_2000/metadata.json` | Feature order, hashes, training settings, and split policy |
| `models/lambdamart_synthetic_2000/same_data_linear_weights.json` | Audit comparison weights; not used by the primary runtime |
| `models/lambdamart_synthetic_2000/README.md` | Bundle hashes, selection, and limitations |

The active bundle is round 3, selected from a bounded three-round comparison
for the highest observed public-set MRR while keeping Hit@10 above the original
Flash baseline. The public 200 was reused for this comparison, so the result is
development evidence and not an unbiased private-set estimate. See the
[comparison report](../techjam-conversational-search/docs/mrr_loss_search_20260901.md).

## Optional applications

| Path | Contents |
|---|---|
| `demo-frontend/src/views/` | Home, chat, evaluation, run history, and settings pages |
| `demo-frontend/src/stores/`, `src/api.ts`, `src/types.ts` | Browser state, HTTP client, and API contracts |
| `demo-frontend/src/locales/` | English and Chinese UI copy |
| `demo-frontend/src/test/` | Frontend behavior tests |
| `demo-frontend/public/` | Referenced workbench and social-preview images |
| `trace-visualizer/app/`, `lib/trace.ts` | Trace UI and schema validation |
| `trace-visualizer/components/ui/` | Only the five UI primitives imported by the viewer |
| `trace-visualizer/scripts/` | Trace conversion helpers and format tests |
| `trace-visualizer/public/favicon.svg` | Viewer icon; no evaluation data is bundled |
| `trace-visualizer/vite.config.ts` | Local viewer build and loopback-only development-server configuration |
| `user-simulator/src/user_simulator/` | Scenario generation, policies, metrics, verbalization, and reporting |
| `user-simulator/configs/` | TechJam and realistic presets |
| `user-simulator/tests/` | Simulator protocol and reporting checks |

Each optional application has its own README or is linked from the root
documentation index. Package manifests, lockfiles, TypeScript configs, lint
configs, and `.gitignore` files support their corresponding application.

## Generated and excluded files

Evaluation runs are written under `techjam-conversational-search/evaluation_runs/`
or `demo_runs/` and are intentionally not tracked. A normal run may contain
`summary.json`, `report.md`, `sessions.jsonl`, `turns.jsonl`, `trace.json`, raw
LLM/ranking logs, and worker shards. These files can contain scenario content,
local paths, and hundreds of megabytes of diagnostics.

Credentials, the organizer catalog, private scenarios, virtual environments,
dependency directories, caches, build output, and test output are also ignored.
The repository contains no frozen historical run and no private judge input.
