@echo off
title TeleLink
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First run - setting up...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
    if errorlevel 1 exit /b 1
)

if not exist "assets\banner.txt" (
    where npx >nul 2>&1
    if not errorlevel 1 (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\banner.ps1"
    )
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
chcp 65001 >nul 2>&1

.venv\Scripts\python.exe -X utf8 -m telelink
exit /b %ERRORLEVEL%
