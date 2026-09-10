"""一次性 launcher：以 DETACHED_PROCESS 派生 cockpit 保活守护进程后自己退出。

目的：让守护进程（pythonw，无窗口）彻底脱离启动它的父进程（agent/命令行）树，
即使父进程/本轮 agent 结束，守护进程仍由系统接管、持续自愈 8090。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHONW = r"C:\Users\cenacai\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"

subprocess.Popen(
    [PYTHONW, "cockpit_keepalive.py", "--daemon", "--interval", "60"],
    cwd=HERE,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    close_fds=True,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
)
sys.exit(0)
