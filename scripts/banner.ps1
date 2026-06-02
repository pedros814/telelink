# Regenerate TeleLink banners (oh-my-logo). Requires Node/npx.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Assets = Join-Path $Root "assets"
$Banner = Join-Path $Assets "banner.txt"
$BannerFilled = Join-Path $Assets "banner.filled.txt"

New-Item -ItemType Directory -Force -Path $Assets | Out-Null

# ASCII-safe (works in classic cmd.exe)
& npx --yes oh-my-logo@latest "TeleLink" ocean --no-color 2>$null | Set-Content -Path $Banner -Encoding ascii

# Unicode filled (Windows Terminal only)
& npx --yes oh-my-logo@latest "TELE\nLINK" ocean --filled --no-color 2>$null | Set-Content -Path $BannerFilled -Encoding utf8

Write-Host "Saved assets\banner.txt (cmd-safe)" -ForegroundColor Green
Write-Host "Saved assets\banner.filled.txt (Windows Terminal)" -ForegroundColor DarkGray
