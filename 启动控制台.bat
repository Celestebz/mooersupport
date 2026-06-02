@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Mooer Support Dashboard

echo =======================================
echo Mooer Support Agent Dashboard
echo =======================================
echo.

:: Check for virtual environment
if exist ".venv\Scripts\activate.bat" (
    echo [INFO] Activating virtual environment...
    call ".venv\Scripts\activate.bat"
) else (
    echo [WARN] .venv not found. Using system Python...
)

:: Check if streamlit is installed
python -c "import streamlit" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Streamlit is not installed!
    echo [INFO] Installing dependencies...
    pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
)

echo [INFO] Starting Dashboard...
echo.
streamlit run dashboard.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Dashboard crashed or failed to start.
    pause
)
