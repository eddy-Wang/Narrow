# Narrow

[中文说明](README.zh-CN.md) · [Judge's file guide](docs/JUDGE_GUIDE.md)

> [!IMPORTANT]
> An **LLM-driven agent is a core part of this submission** — please connect an
> API key to experience the full multi-turn behavior. The agent targets an
> **OpenAI-compatible** chat-completions endpoint (any compatible provider via
> `DEEPSEEK_BASE_URL`); we recommend **DeepSeek V4 Flash**. If you need a key,
> contact [tianshuo001@e.ntu.edu.sg](mailto:tianshuo001@e.ntu.edu.sg) or
> [ziyue007@e.ntu.edu.sg](mailto:ziyue007@e.ntu.edu.sg).

Conversational product search across multiple turns. DeepSeek interprets user
requirements and decides when to ask follow-up questions. Lexical, semantic,
and attribute retrieval produce candidates, which LambdaMART reranks. The
repository includes pretrained weights, an evaluator, a shopping workbench,
and a trace viewer.

<p align="center">
  <img src="demo-frontend/public/hero-shopping-wide-v2.png" alt="Narrow shopping workbench interface" width="760" />
</p>

## Submission at a glance

| Item | Current submission |
|---|---|
| Judge entry | `techjam-conversational-search/submission_agent.py` exports `Agent` |
| One-command evaluation | `run_evaluation.ps1` |
| Primary runtime | DeepSeek V4 Flash for understanding/dialogue and a frozen LambdaMART reranker |
| Required local data | Organizer catalog plus a compatible JSONL scenario set |
| Public 200 development result | Hit@10 **98.5%**, MRR **0.543222**, MTTC **2.075**, technical score **0.833967** |
| Network requirement | The primary path requires a configured DeepSeek API key; online failures are not replaced with offline output |
| Estimated model cost | Priced on DeepSeek V4 Flash off-peak rates; see the cost note below |

The public 200 was used for bounded model selection, so these figures are
development evidence rather than an estimate of private-set performance. The
selected model, its feature schema, hashes, and limitations are included in
the repository.

### Estimated model cost

The primary path calls DeepSeek V4 Flash for intent understanding and dialogue.
At the official off-peak rates effective 2026-08-16 — input (cache miss) ¥1.5
per 1M tokens and output ¥4.5 per 1M tokens; peak hours double these figures —
a run's cost is:

```text
cost_CNY = (prompt_tokens / 1e6) * 1.5 + (completion_tokens / 1e6) * 4.5
```

`prompt_tokens` and `completion_tokens` are the `reported_token_usage` values
written to `summary.json` after each run. Fill in the values from the latest
run: ~___ prompt + ~___ completion tokens ≈ ¥___ per 200-scenario public run.
Prices may change; confirm the official DeepSeek pricing page before budgeting.

| Path | Purpose | Required for CLI scoring? |
|---|---|---|
| `techjam-conversational-search/` | Agent, evaluator, tests, data schema, and active model | Yes |
| `demo-frontend/` | Optional interactive workbench | No |
| `trace-visualizer/` | Optional local inspection of a generated `trace.json` | No |
| `user-simulator/` | Optional alternative simulation protocols | No |
| `docs/` | Judge map, testing, and trace format | Reference |

## Quickstart

Requirements: Python 3.12 and uv. Commands below use Windows PowerShell.
Node.js is not needed for the agent or command-line evaluation.

### 1. Install

```powershell
git clone https://github.com/zhouziyueharry-droid/tiktok_project_4.git
cd tiktok_project_4
uv sync --locked --project techjam-conversational-search --extra web --extra ltr --extra deepseek --group dev
Copy-Item techjam-conversational-search/.env.example techjam-conversational-search/.env
New-Item -ItemType Directory -Force techjam-conversational-search/data/test | Out-Null
```

Skip cloning if you already have the source. Do not copy over an existing
`.env`.

### 2. Configure the API

Edit `techjam-conversational-search/.env`:

```dotenv
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
SHOPPING_AGENT_ENABLE_LLM=true
SHOPPING_DENSE_BACKEND=local
LANGSMITH_TRACING=false
```

Keep the key in this file; no Python or frontend changes are needed. Existing
system environment variables take precedence over `.env`.
`SHOPPING_DENSE_BACKEND=local` keeps retrieval local; it does not disable LLM
calls. Never include `.env` in a submission or shared archive. The examples
use Flash for the latest evaluation; the model remains configurable.

### 3. Add the data

```text
techjam-conversational-search/
├── .env
├── data/
│   ├── catalog.jsonl          # Product catalog; decompress .gz first
│   └── test/
│       └── users.jsonl        # User scenarios to evaluate
└── models/
    └── lambdamart_synthetic_2000/   # Active pretrained bundle
```

Use the organizer-provided product catalog. Scenarios use the JSONL format
of `data/public_set.jsonl`; see the [data format](techjam-conversational-search/data/README.md).
`data/test/` is ignored by Git. To try the included public set:

```powershell
if (-not (Test-Path techjam-conversational-search/data/test/users.jsonl)) {
    Copy-Item techjam-conversational-search/data/public_set.jsonl techjam-conversational-search/data/test/users.jsonl
}
```

### 4. Run

From the repository root:

```powershell
.\run_evaluation.ps1
```

This evaluates all supplied scenarios with **DeepSeek + LambdaMART**, using
four workers by default. The terminal shows input paths, model selection,
worker starts, completed scenarios, current turns, elapsed time, and an ETA.
It prints the metrics and output directory when finished.

```text
started shard 1/4: samples=50 pid=...
[progress] 36/200 (18.0%) elapsed=00:02:10 ETA~00:09:52
  w1=9/50 last:public_0033/turn2 | ...
finished shard 1/4: exit=0 remaining=3
```

To reduce concurrency, use `.\run_evaluation.ps1 -Workers 1`. Press Ctrl+C to
stop all evaluation workers; written logs remain available. Online
evaluation calls the configured API and incurs usage charges.

## Results

Each run writes to `techjam-conversational-search/evaluation_runs/test/<timestamp>/`.
Previous results are retained. `evaluation_runs/test/LATEST.txt` identifies
the most recent output directory.

| File | Contents |
|---|---|
| `summary.json` / `report.md` | Hit@10, MRR, MTTC, technical score, and token usage |
| `sessions.jsonl` / `turns.jsonl` | Per-session outcomes, turn messages, and recommendations |
| `trace.json` | Diagnostics for import into the trace viewer |
| `node_traces.jsonl` | Intent state, retrieval stages, and ranking candidates |
| `llm_calls.jsonl` / `rank_calls.jsonl` | LLM requests/responses and reranking records |
| `run_config.json` | Model, data paths, and evaluation parameters |
| `shards/` | Worker-specific inputs, logs, and raw results |

Errors include English and Chinese explanations. Startup errors identify a
file or parameter; worker crashes include a summary and log path; turn errors
identify the sample, turn, stage, and underlying cause. Full error logs remain
in `shards/shard_*/stderr.log`. Logs contain test content and should be handled
with the same care as the test data.

A completed run with failed turns retains its results, records
`failed_turn_count` in `summary.json`, and exits with a nonzero status. A
fully successful run exits with 0. Online errors are not silently replaced
with offline results.

## Python interface

From `techjam-conversational-search/`, use the project Python environment:

```python
from dotenv import load_dotenv
from submission_agent import Agent
from shopping_agent.ranking.lambdamart import LambdaMARTReranker

load_dotenv(".env")
agent = Agent(
    catalog_path="data/catalog.jsonl",
    reranker=LambdaMARTReranker("models/lambdamart_synthetic_2000"),
)
agent.reset("session-1", user_profile={})
result = agent.respond(
    session_id="session-1",
    user_message="I need waterproof shoes under $100.",
    turn=1,
    top_k=10,
)
print(result)
agent.release_session("session-1")
```

`respond` returns `message`, `ask_attribute`, ranked `recommendations`, and
token `usage`. Products use `parent_asin` identifiers. Reuse the session ID
and increment `turn` within a conversation. Ground-truth targets are read by
the evaluator and are not passed to the agent.

The local rule-based path and Precise reranker remain available for debugging
and comparisons. The main evaluation entry uses online understanding,
online dialogue, and LambdaMART. Online exceptions are recorded as failures.

## Workbench and trace viewer

Use a compatible Node.js version, 22.13 or newer. From the repository root:

```powershell
npm --prefix demo-frontend ci --no-audit --no-fund
npm --prefix trace-visualizer ci --no-audit --no-fund
.\scripts\run_demo.ps1 -SkipInstall
```

- Workbench: [http://127.0.0.1:5173](http://127.0.0.1:5173). Select and save
  **DeepSeek + LambdaMART** in settings for chat and browser evaluation.
- Trace viewer: [http://127.0.0.1:3000](http://127.0.0.1:3000). Import the CLI run's `trace.json`.
- API health: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health).

CLI results are not automatically added to browser run history. Native and
TechJam workbench evaluations use the public set. Use `run_evaluation.ps1`
for a custom user test set.

## Documentation

| Document | Purpose |
|---|---|
| [Judge's file guide](docs/JUDGE_GUIDE.md) | Complete repository map and required/optional files |
| [Tests and evaluation](docs/TESTING.md) | Offline checks, online evaluation, and generated artifacts |
| [Agent architecture](techjam-conversational-search/docs/agent_architecture.md) | Runtime graph, state, retrieval, and reliability boundaries |
| [LambdaMART training](techjam-conversational-search/docs/lambdamart_training.md) | Data separation, features, training, and reproduction |
| [MRR training](techjam-conversational-search/docs/mrr_training.md) | Current loss objective and bounded comparison procedure |
| [Flash comparison](techjam-conversational-search/docs/mrr_loss_search_20260901.md) | Public development scores, selection rule, and limitations |
| [Demo workbench](demo-frontend/README.md) | Optional browser UI, local API behavior, and file map |
| [Trace viewer](trace-visualizer/README.md) | Local trace inspection and viewer file map |
| [User simulator](user-simulator/README.md) | Optional TechJam and realistic simulation protocols |
| [Trace format](docs/TRACE_JSON_FORMAT.md) | Portable `trace.json` schema |
| [Data attribution](techjam-conversational-search/DATA_ATTRIBUTION.md) | Source data and usage context |

Current bundle provenance is recorded in
[`models/lambdamart_synthetic_2000/README.md`](techjam-conversational-search/models/lambdamart_synthetic_2000/README.md).
Generated evaluation runs are intentionally excluded from Git because they can
contain scenario content and large raw traces.
