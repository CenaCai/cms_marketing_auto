@echo off
REM ============================================================
REM  Campaign Cockpit 一键启动  ->  http://127.0.0.1:8090/
REM  用法：双击本文件。服务是 detached 进程，关闭窗口不会停止。
REM  说明：在 WorkBuddy 后台任务里启动的 cockpit 会随会话结束被回收，
REM        需要长期开着时就用本脚本启动（脱离 WorkBuddy 会话）。
REM ============================================================
SET PY=C:\Users\cenacai\.workbuddy\binaries\python\versions\3.13.12\python.exe
SET WD=C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc

netstat -ano | findstr ":8090" | findstr "LISTENING" >nul
IF ERRORLEVEL 1 (
  echo Starting cockpit on 8090 ...
  cd /d "%WD%"
  start "" "%PY%" -u cockpit.py
) ELSE (
  echo Cockpit already running on 8090.
)

echo.
echo Cockpit should be up at  http://127.0.0.1:8090/
timeout /t 3 >nul
