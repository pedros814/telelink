# TeleLink one-time setup (free, local, Windows)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "TeleLink setup" -ForegroundColor Cyan

$Python = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py -3" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = "python" }
else {
    Write-Host "Install Python 3.11+ from https://www.python.org/downloads/ (check Add to PATH)" -ForegroundColor Red
    exit 1
}

Invoke-Expression "$Python -m venv .venv"
$Py = ".\.venv\Scripts\python.exe"
& $Py -m pip install --upgrade pip
& $Py -m pip install -r requirements.txt

if (-not (Test-Path "config.yaml")) {
    Copy-Item config.example.yaml config.yaml
    Write-Host "Created config.yaml - edit owner block and data/contacts.jsonl" -ForegroundColor Yellow
}

New-Item -ItemType Directory -Force -Path "data" | Out-Null
if (-not (Test-Path "data\contacts.jsonl")) {
    Copy-Item assets\contacts.example.jsonl data\contacts.jsonl
    Write-Host "Created data\contacts.jsonl from template" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Optional OCR (screenshots):" -ForegroundColor Cyan
Write-Host "  winget install UB-Mannheim.TesseractOCR"
Write-Host "  Then set ocr.enabled: true in config.yaml"
Write-Host ""
Write-Host "Enable notification access:" -ForegroundColor Cyan
Write-Host "  start ms-settings:privacy-notifications"
Write-Host ""
Write-Host "Run listener:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\python.exe -m telelink doctor"
Write-Host "  .\.venv\Scripts\python.exe -m telelink listen"
