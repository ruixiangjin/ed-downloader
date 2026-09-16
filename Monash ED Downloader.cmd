@echo off
setlocal
chcp 65001 >nul
title Monash ED Downloader
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Monash ED Downloader.ps1"
set "launcher_status=%ERRORLEVEL%"

echo.
echo Press any key to close this window...
pause >nul
exit /b %launcher_status%
