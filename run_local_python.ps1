$PythonArgs = $args
$ErrorActionPreference = "Stop"
$ProjectRoot = Join-Path $PSScriptRoot "techjam-conversational-search"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PreviousPythonPath = $env:PYTHONPATH
$PreviousBytecode = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONPATH = (Join-Path $ProjectRoot "src") + [IO.Path]::PathSeparator + $ProjectRoot
    $env:PYTHONDONTWRITEBYTECODE = "1"
    Push-Location $ProjectRoot
    try {
        & $PythonExe @PythonArgs
        if ($LASTEXITCODE -ne 0) { throw "Python exited with code $LASTEXITCODE" }
    } finally { Pop-Location }
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
    $env:PYTHONDONTWRITEBYTECODE = $PreviousBytecode
}
