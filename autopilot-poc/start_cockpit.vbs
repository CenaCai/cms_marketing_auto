' 双击本文件即可在【用户会话】中常驻 cockpit 8090（无窗口、后台进程）。
' 进程归属你的 Windows 会话，不被 WorkBuddy 沙箱回收，可持续自愈。
' 等价于：pythonw.exe spawn_cockpit_daemon.py（DETACHED 派生守护进程 -> 每 60s 自愈 8090）
Set W = CreateObject("WScript.Shell")
PYTHONW = "C:\Users\cenacai\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
LAUNCHER = "C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc\spawn_cockpit_daemon.py"
W.Run """" & PYTHONW & """ """ & LAUNCHER & """", 0, False
