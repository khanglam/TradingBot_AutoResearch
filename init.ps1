# init.ps1 — bootstrap on Windows (PowerShell). Idempotent.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "[init] === TradingBot AutoResearch init (Windows) ==="

$py = $null
foreach ($cand in @("py -3.12", "py -3.11", "python3.12", "python3.11")) {
    $parts = $cand -split " "
    $exe = $parts[0]
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        $check = & $exe $parts[1..($parts.Length-1)] --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            $py = $cand
            break
        }
    }
}
if (-not $py) {
    Write-Error @"
[init] ERROR: Python 3.11 or 3.12 not found.
  Install from https://www.python.org/downloads/ (check 'Add to PATH').
"@
    exit 1
}
Write-Host "[init] using $py"

if (-not (Test-Path ".venv")) {
    $parts = $py -split " "
    & $parts[0] $parts[1..($parts.Length-1)] -m venv .venv
    Write-Host "[init] created .venv"
}

$venvPy = ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt --quiet
Write-Host "[init] python deps installed"

& $venvPy scripts\bootstrap.py
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
