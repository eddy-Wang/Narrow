# Tests and Evaluation

[Chinese](TESTING.zh-CN.md) · [Root README](../README.md) · [Data format](../narrow-shopping-agent/data/README.md)

Run all PowerShell commands below from the repository root.

## Online evaluation

Configure `.env` and provide `data/catalog.jsonl` and `data/test/users.jsonl`
as described in the root README, then run:

```powershell
.\run_evaluation.ps1
```

The default run uses OpenAI plus LambdaMART with four workers. Progress is
refreshed every five seconds. The model name comes from `OPENAI_MODEL`.
Outputs are written under the backend's `evaluation_runs/test/<timestamp>/`.

Call the underlying script when you need custom paths or parameters:

```powershell
.\run_local_python.ps1 scripts/evaluate_parallel_with_traces.py `
  --catalog 'C:\datasets\catalog.jsonl' `
  --dataset 'C:\datasets\users.jsonl' `
  --ltr-ranker lambdamart --ltr-model-dir models/lambdamart_synthetic_2000 `
  --workers 4 --progress-interval 5 --candidate-limit 0 `
  --output-root evaluation_runs/custom
```

Use `--model gpt-5.4` to override the configured model name.
`--candidate-limit 0` records complete candidate snapshots. A positive value
truncates only diagnostic capture; it does not change retrieval or ranking.
`run_local_python.ps1` changes into the backend directory, so relative input
and output paths are resolved from there.

The parallel script performs online evaluation. For single-process debugging,
use `scripts/evaluate_with_traces.py`; its `--llm` and `--no-llm` flags control
model calls. The main evaluation entry never silently switches to offline mode.

## Code tests

Use the existing Python environment, or install it with the root README first.
These tests use controlled model responses and do not call the live API:

```powershell
New-Item -ItemType Directory -Force test_results | Out-Null
$env:SHOPPING_AGENT_ENABLE_LLM = "false"
$env:SHOPPING_DENSE_BACKEND = "local"
$env:LANGSMITH_TRACING = "false"

.\run_local_python.ps1 -m pytest -c pyproject.toml tests ../user-simulator/tests `
  -o "pythonpath=. src ../user-simulator/src" -q -p no:cacheprovider `
  --basetemp .pytest-run-regression --junitxml=../test_results/python.xml

npm --prefix demo-frontend test -- --reporter=default --reporter=junit --outputFile=../test_results/frontend.xml
node --experimental-strip-types --test --test-reporter=tap `
  --test-reporter-destination=test_results/trace.tap `
  trace-visualizer/scripts/tests/trace-format.test.mjs
```

See the [root README](../README.md) for frontend installation and startup.
Code tests do not produce business Hit@10 or MRR results.

## Browser evaluation

The workbench's Native and Benchmark modes use `data/public_set.jsonl`.
Realistic mode generates shopping needs from the catalog. New runs are stored
under `demo_runs/<run-id>/`; the respective limits are 200, 200, and 100
scenarios, and only one job runs at a time.

Custom CLI scenarios are not uploaded through the browser. CLI results are not
automatically registered in browser history; import the generated `trace.json`
directly into the trace viewer.

## Artifact handling

Evaluation directories, workbench runs, raw LLM calls, and complete candidate
traces are not committed to Git. They may contain test content, local paths,
and hundreds of megabytes of data. When evidence must be shared, prefer the
current commit's reviewed `report.md`, `summary.json`, and `trace.json`. Never
upload private test inputs or credentials.
