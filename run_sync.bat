@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo sync_email_status.py is deprecated because it can reset processed emails and create duplicate drafts.
echo Run ".venv\Scripts\python.exe sync_email_status.py --force" manually only after reviewing the state.
pause
