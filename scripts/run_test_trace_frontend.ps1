[CmdletBinding()]
param(
    [int]$Workers = 0,
    [string]$Model = "deepseek-v4-pro",
    [ValidateSet("precise", "fallback", "bge")]
    [string]$Reranker = "precise",
    # 0 records every candidate; positive limits are for explicit debugging only.
    [ValidateRange(0, 2147483647)]
    [int]$CandidateLimit = 0,
    [ValidateRange(1, 3600)]
    [int]$ProgressInterval = 10,
    [string]$OutputRoot = "evaluation_runs/parallel_pro_200",
    [switch]$TestsOnly,
    [switch]$SkipTests,
    [switch]$SkipEvaluation,
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$AgentRoot = Join-Path $RepoRoot "techjam-conversational-search"
$FrontendRoot = Join-Path $RepoRoot "trace-visualizer"
$PythonExe = Join-Path $AgentRoot ".venv\Scripts\python.exe"

if ($TestsOnly -and $SkipTests) {
    throw "TestsOnly cannot be combined with SkipTests."
}

if ($Workers -le 0) {
    $Workers = [Environment]::ProcessorCount
}
if ($Workers -lt 1) {
    throw "Workers must be at least 1."
}
if (-not (Test-Path -LiteralPath $AgentRoot)) {
    throw "Agent project not found: $AgentRoot"
}
if (-not (Test-Path -LiteralPath $FrontendRoot)) {
    throw "Trace frontend not found: $FrontendRoot"
}

function Invoke-ProjectPython {
    param([string[]]$PythonArgs)
    if (Test-Path -LiteralPath $PythonExe) {
        & $PythonExe @PythonArgs
    }
    elseif (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv run python @PythonArgs
    }
    else {
        throw "Neither .venv Python nor uv is available. Run 'uv sync --extra deepseek --group dev' first."
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

Push-Location $AgentRoot
try {
    if (-not $SkipTests) {
        Write-Host "[1/4] Running unit, integration, and regression tests..."
        $PreviousReranker = $env:SHOPPING_AGENT_RERANKER
        try {
            # Regression fixtures exercise the historical default; BGE unit tests
            # inject their own fake scorer and must not download a model.
            $env:SHOPPING_AGENT_RERANKER = "precise"
            # Never reuse sandbox-owned temp/cache directories across accounts.
            # Use a fresh direct child of the project, not the old .pytest_tmp parent.
            $PytestTemp = Join-Path $AgentRoot (".pytest-run-" + [Guid]::NewGuid().ToString("N"))
            Write-Host "Test temporary directory: $PytestTemp"
            Invoke-ProjectPython @(
                "-m", "pytest", "tests", "-q",
                "--basetemp=$PytestTemp", "-p", "no:cacheprovider"
            )
        }
        finally {
            $env:SHOPPING_AGENT_RERANKER = $PreviousReranker
        }
    }

    if ($TestsOnly) {
        Write-Host "Tests complete. Evaluation, diagnostics replay, and frontend build were not started."
        return
    }

    if (-not $SkipEvaluation) {
        Write-Host "[2/4] Running official evaluator semantics with $Workers traced LLM workers..."
        $PreviousEvaluationReranker = $env:SHOPPING_AGENT_RERANKER
        try {
            # A temporary experiment must not leave BGE enabled in this shell.
            $env:SHOPPING_AGENT_RERANKER = $Reranker
            Invoke-ProjectPython @(
                "scripts\evaluate_parallel_with_traces.py",
                "--workers", "$Workers",
                "--model", $Model,
                "--candidate-limit", "$CandidateLimit",
                "--progress-interval", "$ProgressInterval",
                "--output-root", $OutputRoot
            )
        }
        finally {
            $env:SHOPPING_AGENT_RERANKER = $PreviousEvaluationReranker
        }
    }
    else {
        Write-Host "[2/4] Reusing the latest completed evaluation."
    }
}
finally {
    Pop-Location
}

$EvaluationRoot = if ([IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot
} else {
    Join-Path $AgentRoot $OutputRoot
}
$LatestFile = Join-Path $EvaluationRoot "LATEST.txt"
if (-not (Test-Path -LiteralPath $LatestFile)) {
    throw "Evaluation LATEST.txt not found: $LatestFile"
}
$RunDir = (Get-Content -LiteralPath $LatestFile -Raw).Trim()

Push-Location $FrontendRoot
try {
    Write-Host "[3/4] Exporting saved Trace for the frontend (no model replay)..."
    Invoke-ProjectPython @(
        (Join-Path $AgentRoot "scripts\export_trace.py"),
        "--run-dir", $RunDir
    )
    Copy-Item -LiteralPath (Join-Path $RunDir "trace.json") -Destination (Join-Path $FrontendRoot "public\diagnostics.json")

    if (-not $SkipFrontendBuild) {
        Write-Host "[4/4] Building the trace frontend..."
        & npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend build failed with exit code $LASTEXITCODE."
        }
    }
    else {
        Write-Host "[4/4] Frontend build skipped."
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Pipeline complete."
Write-Host "Evaluation: $RunDir"
Write-Host "Frontend data: $(Join-Path $FrontendRoot 'public\diagnostics.json')"
Write-Host "Preview: cd '$FrontendRoot'; npm run dev"
