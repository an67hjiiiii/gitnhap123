@echo off
rem Nhấp đúp để chạy OrchestrIQ Studio (Ollama + Backend + Giao diện) rồi mở trình duyệt.
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev\start-all.ps1" %*
if errorlevel 1 pause
