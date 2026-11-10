@echo off
REM ZeroNoShow bridge: sends ZeroNoShow SMS from your iPhone through Phone Link.
cd /d "%~dp0"
title TeleLink - ZeroNoShow bridge
".venv\Scripts\python.exe" -m telelink zns run
pause
