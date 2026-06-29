@echo off
chcp 65001 >nul
echo ============================================
echo   MOOER Support - React Console
echo   http://localhost:5173
echo ============================================

cd /d "%~dp0\web"

if not exist node_modules (
  echo.
  echo Installing frontend dependencies...
  call npm.cmd install
)

echo.
echo Starting React console...
call npm.cmd run dev

pause
