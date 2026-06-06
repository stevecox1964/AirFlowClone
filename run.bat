@echo off
setlocal

set ROOT=%~dp0

echo Stopping any prior AirFlowClone processes...

REM Kill prior console windows by title (cascades to child python/node via /T)
taskkill /F /T /FI "WINDOWTITLE eq AirFlowClone Backend"  >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq AirFlowClone Frontend" >nul 2>&1

REM Belt-and-suspenders: kill anything still bound to our ports
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

echo Starting AirFlowClone...
echo   Backend  -^> http://127.0.0.1:8000
echo   Frontend -^> http://127.0.0.1:5173
echo.
echo Two console windows will open. Close either to stop that service.
echo.

start "AirFlowClone Backend" cmd /k "cd /d %ROOT%backend && .venv\Scripts\python.exe -m airflowclone.main"

start "AirFlowClone Frontend" cmd /k "cd /d %ROOT%frontend && npm run dev"

endlocal
