@echo off
rem Nhấp đúp để tắt OrchestrIQ Studio (backend và giao diện).
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev\stop-all.ps1" %*
pause
