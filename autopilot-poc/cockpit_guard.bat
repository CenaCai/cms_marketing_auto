@echo off
REM ============================================================
REM  Campaign Cockpit 自愈守护启动器（双击运行，无控制台窗口）
REM
REM  必须在 Windows 文件管理器中**双击本文件**启动，不要在
REM  WorkBuddy 会话里用命令拉起——沙箱会回收其所有子进程。
REM
REM  启动后：cockpit_guard.py 会持续检测 http://localhost:8090/，
REM  一旦服务掉线就自动重拉，并把记录写进 cockpit_guard.log。
REM
REM  关闭方式：任务管理器结束 cockpit_guard.py / pythonw.exe，
REM  或直接结束它拉起的 cockpit.py 进程（守护会在下一个周期再拉起，
REM  所以想彻底停就先结束守护自己）。
REM ============================================================
setlocal
set "WD=C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc\autopilot-poc"
set "GUARD_PY=%WD%\cockpit_guard.py"
set "PYW=C:\Users\cenacai\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"

if not exist "%PYW%" (
  echo [ERROR] pythonw.exe not found: %PYW%
  pause
  exit /b 1
)
if not exist "%GUARD_PY%" (
  echo [ERROR] cockpit_guard.py not found: %GUARD_PY%
  pause
  exit /b 1
)

echo Starting cockpit self-healing guard (background, no window) ...
start "" "%PYW%" "%GUARD_PY%"
echo Done. Open http://localhost:8090/  (guard keeps it alive; logs in cockpit_guard.log)
exit /b 0
