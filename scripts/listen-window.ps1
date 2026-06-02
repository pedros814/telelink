# Start TeleLink notification watcher in a new console window.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
$env:TELELINK_WATCHER = "1"

Start-Process -FilePath $py `
    -ArgumentList "-X", "utf8", "-m", "telelink", "watcher", "--foreground" `
    -WorkingDirectory $Root
