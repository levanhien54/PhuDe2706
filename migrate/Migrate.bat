@echo off
REM Double-click de mo giao dien di chuyen du an (croc P2P).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0migrate-gui.ps1"
