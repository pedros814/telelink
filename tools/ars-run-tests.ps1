<#
.SYNOPSIS
Phase 4 CI gate: run pytest tests/test_ars*.py, check tools/ars-fixtures.
#>

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    Write-Host "Activating venv..."
    . ".\.venv\Scripts\Activate.ps1"
}

Write-Host "Running ARS unit tests..."
$testFiles = Get-ChildItem "tests\test_ars*.py" | Select-Object -ExpandProperty FullName
.\.venv\Scripts\python.exe -m pytest $testFiles

if ($LASTEXITCODE -ne 0) {
    Write-Error "Tests failed!"
    exit 1
}

Write-Host "Checking ARS fixtures..."
if (-Not (Test-Path "tools/ars-fixtures/README.md")) {
    Write-Warning "Fixtures directory seems incomplete."
}

Write-Host "All ARS CI checks passed!"
exit 0
