# Install global `telelink` command on PATH (Windows)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bin = Join-Path $env:LOCALAPPDATA "Programs\TeleLink"
$Launcher = Join-Path $Bin "telelink.cmd"
$Py = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Py)) {
    Write-Host "Virtual env not found. Run .\scripts\setup.ps1 first." -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $Bin | Out-Null

$cmd = @"
@echo off
set "ROOT=$Root"
cd /d "%ROOT%"
"%ROOT%\.venv\Scripts\python.exe" -m telelink %*
"@

Set-Content -Path $Launcher -Value $cmd -Encoding ASCII

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$Bin*") {
    $newPath = if ($userPath) { "$userPath;$Bin" } else { $Bin }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    $env:Path = "$env:Path;$Bin"
    Write-Host "Added to user PATH: $Bin" -ForegroundColor Green
} else {
    Write-Host "Already on PATH: $Bin" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Installed: $Launcher" -ForegroundColor Green
Write-Host "Open a new terminal, then run:  telelink" -ForegroundColor Cyan
Write-Host "Re-run this script if you move the TeleLink folder." -ForegroundColor DarkGray
