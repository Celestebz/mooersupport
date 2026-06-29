@echo off
cd /d "%~dp0"
"C:\Users\USER\.workbuddy\binaries\python\envs\mooer-api\Scripts\python.exe" -m uvicorn api.main:app --host 0.0.0.0 --port 8100 > "%~dp0logs\api_stdout.log" 2> "%~dp0logs\api_stderr.log"
