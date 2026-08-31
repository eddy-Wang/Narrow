[CmdletBinding()]
param([int]$Workers = 4)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'run_local_python.ps1') scripts/evaluate_parallel_with_traces.py `
    --catalog data/catalog.jsonl `
    --dataset data/test/users.jsonl `
    --ltr-ranker lambdamart --ltr-model-dir models/lambdamart_synthetic_2000 `
    --workers $Workers --progress-interval 5 `
    --output-root evaluation_runs/test
