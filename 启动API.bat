@echo off
chcp 65001 >nul
REM Start MOOER Support API server
echo ============================================
echo   MOOER Support API Server
echo   Docs: http://localhost:8100/docs
echo ============================================

cd /d "%~dp0"

set VENV=C:\Users\USER\.workbuddy\binaries\python\envs\mooer-api

"%VENV%\Scripts\python.exe" -m uvicorn api.main:app --host 0.0.0.0 --port 8100 --reload

pause
