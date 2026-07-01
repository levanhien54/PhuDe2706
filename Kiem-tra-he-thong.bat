@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0preflight_check.ps1" -Root "%~dp0."
echo.
pause
