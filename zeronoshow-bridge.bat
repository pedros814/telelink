@echo off
REM ZeroNoShow : pont iPhone (SMS, appels, WhatsApp) - relance auto par la tache "ZeroNoShow - pont iPhone".
cd /d "%~dp0"
title ZeroNoShow - pont iPhone
".venv\Scripts\python.exe" -m telelink zns run
REM 3 = un pont tourne deja (rien a faire) ; 4 = redemarrage apres mise a jour
if %errorlevel%==3 exit /b 0
if %errorlevel%==4 exit /b 0
pause
