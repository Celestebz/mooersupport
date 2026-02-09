@echo off
title Mooer Email Automation Service
echo Starting Mooer Email Automation Service...
echo Press Ctrl+C to stop the service.
echo.

:loop
echo [%date% %time%] Starting email automation process...
python email_automation.py --interval 5
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Process exited with error code %ERRORLEVEL%.
    echo Restarting in 10 seconds...
    timeout /t 10
    goto loop
)

echo.
echo Process stopped normally.
pause