@echo off
REM Start MOOER Support Dashboard
echo ============================================
echo   MOOER Support Dashboard
echo   http://localhost:8501
echo ============================================

cd /d "%~dp0"

set VENV=C:\Users\USER\.workbuddy\binaries\python\envs\mooer-api

"%VENV%\Scripts\python.exe" -m streamlit run dashboard.py --server.port 8501

pause
