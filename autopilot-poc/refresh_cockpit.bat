@echo off
REM 刷新 autopilot-poc 驾驶舱 (:8090)
REM cockpit.py 在「两层」路径 autopilot-poc\autopilot-poc\ 下（一层路径不存在，勿用错）。
REM 先按进程名杀，再按端口 8090 兜底杀，确保旧进程释放端口。
taskkill /F /IM pythonw.exe 2>nul
for /f "tokens=5" %%a in ('netstat -aon ^| findstr /i ":8090" ^| findstr LISTENING') do taskkill /F /PID %%a 2>nul
timeout /t 1 >nul
start "" "C:\Users\cenacai\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe" "C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc\autopilot-poc\cockpit.py"
echo 已尝试重启 :8090，稍候刷新 http://localhost:8090/
