@echo off
chcp 65001 >nul
echo ============================================
echo   MOOER Support - Start All Services
echo ============================================
echo.
echo Starting:
echo   1. API Server (port 8100)
echo   2. Dashboard (port 8501)
echo.
echo Press any key to begin...
pause >nul

cd /d "%~dp0"

set VENV=C:\Users\USER\.workbuddy\binaries\python\envs\mooer-api

echo.
echo [1/2] Starting API Server...
start "MOOER-API" "%VENV%\Scripts\python.exe" -m uvicorn api.main:app --host 0.0.0.0 --port 8100

echo [2/2] Starting Dashboard...
echo Wait 3s for API to be ready...
timeout /t 3 /nobreak >nul

start "MOOER-Dashboard" "%VENV%\Scripts\python.exe" -m streamlit run dashboard.py --server.port 8501

echo.
echo ============================================
echo   API:       http://localhost:8100/docs
echo   Dashboard: http://localhost:8501
echo ============================================
echo.
echo Close API and Dashboard windows to stop.
echo.
pause
