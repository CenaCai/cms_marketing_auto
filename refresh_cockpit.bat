@echo off
REM ============================================================
REM  Refresh cockpit (:8090). Kills the 8090 listener, waits for
REM  the port to release, clears stale bytecode, then starts a
REM  fresh instance. Use this instead of health-check launchers
REM  that skip restart when the old process is still "healthy".
REM  If the old server was started As Administrator, right-click
REM  this file -> Run as administrator.
REM ============================================================
setlocal
set "WD=C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc\autopilot-poc"
set "PY=C:\Users\cenacai\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
cd /d "%WD%"

echo [1/3] stopping any process on 8090 ...
for /f "tokens=5" %%p in ('netstat -ano -p TCP ^| findstr ":8090" ^| findstr "LISTENING"') do (
  taskkill /PID %%p /F >nul 2>&1
)
timeout /t 3 /nobreak >nul

echo [2/3] clearing __pycache__ ...
if exist "__pycache__" rmdir /s /q "__pycache__" >nul 2>&1

echo [3/3] starting cockpit ...
start "" "%PY%" cockpit.py --port 8090
timeout /t 3 /nobreak >nul
powershell -NoProfile -Command "try { $c = (Invoke-WebRequest -UseBasicParsing http://localhost:8090/ -TimeoutSec 5).StatusCode; Write-Host ('self-check HTTP ' + $c) } catch { Write-Host 'self-check failed: old server may still hold 8090; right-click Run as administrator.' }"
echo Refresh http://localhost:8090/
