@echo off
cd /d "%~dp0"

:: Already elevated?
net session >nul 2>&1
if %errorLevel% equ 0 (
    call "%~dp0start-telelink.bat"
    exit /b %ERRORLEVEL%
)

:: Ask for admin, then run the real launcher
echo TeleLink needs administrator access (firewall / notifications).
echo.
powershell -NoProfile -Command "Start-Process -FilePath '%~dp0start-telelink.bat' -Verb RunAs -WorkingDirectory '%~dp0'"
exit /b 0
