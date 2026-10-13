@echo off
rem Double-clickable wrapper for Install.ps1 (bypasses execution policy)
rem for this script only.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1" %*
pause
