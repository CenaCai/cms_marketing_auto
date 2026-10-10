@echo off
REM ============================================================
REM  Campaign Cockpit launcher  ->  http://localhost:8090/
REM  Double-click to (re)start. Kills any stale 8090 listener,
REM  waits for the OS to release the port (fixes "restart does
REM  nothing" caused by the Address-already-in-use race), clears
REM  stale bytecode, then launches a fresh detached instance.
REM  If the OLD server was started As Administrator, a normal
REM  double-click cannot kill it: right-click -> Run as admin.
REM ============================================================
setlocal
set "WD=C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc\autopilot-poc"
set "PY=C:\Users\cenacai\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"

if not exist "%PY%" (
  echo [ERROR] pythonw.exe not found: %PY%
  pause
  exit /b 1
)
cd /d "%WD%"

REM 1) Free port 8090: kill whatever is listening on it.
for /f "tokens=5" %%p in ('netstat -ano -p TCP ^| findstr ":8090" ^| findstr "LISTENING"') do (
  echo [1] stopping stale pid %%p on 8090
  taskkill /PID %%p /F >nul 2>&1
)

REM 2) Wait for the OS to release the socket (race fix).
echo [2] waiting for port 8090 to release ...
timeout /t 3 /nobreak >nul

REM 3) Clear stale bytecode so new code cannot load an old .pyc.
if exist "__pycache__" (
  echo [3] clearing __pycache__
  rmdir /s /q "__pycache__" >nul 2>&1
) else (
  echo [3] no __pycache__ to clear
)

REM 4) Launch a fresh detached instance.
echo [4] starting cockpit (new code) on http://localhost:8090/
start "" "%PY%" cockpit.py --port 8090

REM 5) Poll until it listens, then self-verify the new code is live.
set /a tries=0
:wait
timeout /t 2 /nobreak >nul
set /a tries+=1
netstat -ano -p TCP | findstr ":8090" | findstr "LISTENING" >nul && goto up
if %tries% geq 20 (
  echo [WARN] cockpit did not listen within 40s. See cockpit_8090.log.
  pause
  exit /b 1
)
goto wait

:up
echo [OK] cockpit is up: http://localhost:8090/
timeout /t 3 /nobreak >nul
powershell -NoProfile -Command "try { $h = (Invoke-WebRequest -UseBasicParsing http://localhost:8090/ -TimeoutSec 5).Content; if ($h -match 'class=\"mautic\"' -and $h -match '>CN<' -and $h -notmatch '>Chinese<') { Write-Host '[VERIFY] new code live: mautic button OK, switcher=CN, channel rows removed.' } else { Write-Host '[VERIFY] page up but fingerprint mismatch - old code may still be serving.' } } catch { Write-Host '[VERIFY] cannot read page.' }"
echo Done. Refresh http://localhost:8090/
