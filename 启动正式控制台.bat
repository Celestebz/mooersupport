@echo off
chcp 65001 >nul
echo ============================================
echo   MOOER Support - API + React Console
echo ============================================
echo.
echo Starting:
echo   1. API Server (port 8100)
echo   2. React Console (port 5173)
echo.
echo Press any key to begin...
pause >nul

cd /d "%~dp0"

set VENV=C:\Users\USER\.workbuddy\binaries\python\envs\mooer-api

echo.
echo [1/2] Starting API Server...
start "MOOER-API" "%VENV%\Scripts\python.exe" -m uvicorn api.main:app --host 0.0.0.0 --port 8100

echo [2/2] Starting React Console...
timeout /t 3 /nobreak >nul
start "MOOER-React-Console" cmd /k "cd /d %~dp0web && if not exist node_modules npm.cmd install && npm.cmd run dev"

echo.
echo ============================================
echo   API:           http://localhost:8100/docs
echo   React Console: http://localhost:5173
echo   Streamlit:     http://localhost:8501 (旧版，按需启动)
echo ============================================
echo.
pause
