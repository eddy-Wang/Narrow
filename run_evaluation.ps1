[CmdletBinding()]
param([int]$Workers = 4)

$ErrorActionPreference = 'Stop'
try {
    & (Join-Path $PSScriptRoot 'run_local_python.ps1') scripts/evaluate_parallel_with_traces.py `
        --catalog data/catalog.jsonl `
        --dataset data/test/users.jsonl `
        --ltr-ranker lambdamart --ltr-model-dir models/lambdamart_synthetic_2000 `
        --workers $Workers --progress-interval 5 `
        --output-root evaluation_runs/test
} catch {
    Write-Host "`n[错误] 评测执行失败。具体原因和日志位置见上方。" -ForegroundColor Red
    Write-Host "[ERROR] Evaluation failed. See the reason and log locations above." -ForegroundColor Red
    Write-Host "[PowerShell] $($_.Exception.Message)" -ForegroundColor DarkRed
    exit 1
}
