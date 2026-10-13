@echo off
rem Double-clickable wrapper for Uninstall.ps1 (bypasses execution policy)
rem for this script only.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Uninstall.ps1" %*
pause
