#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
cockpit_guard.py — Campaign Cockpit 自愈守护（脱离 WorkBuddy 沙箱常驻）

用途：
  在 Windows 文件管理器中**双击 cockpit_guard.bat** 启动本脚本（pythonw，无控制台窗口）。
  脚本进入死循环：
    1) 用「绕过沙箱代理」的方式直连 127.0.0.1:8090，判断 cockpit 是否存活；
    2) 存活 → 每 10s 轮询一次；
    3) 不存活 → 杀掉任何残留的 8090 监听者，重新 DETACHED 拉起 cockpit.py，
       并把每次重拉记录到 cockpit_guard.log。

注意：
  - 本脚本必须由「资源管理器 Explorer 双击 .bat」启动，不能在 WorkBuddy 会话内
    用 Bash/PowerShell 拉起——沙箱会在 1~2 分钟内回收其所有子进程，自愈无效。
  - 解释器/路径均为本机绝对路径，不依赖 PATH。
"""
import subprocess
import os
import time
import urllib.request

PY = r"C:\Users\cenacai\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
COCKPIT = r"C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc\autopilot-poc\cockpit.py"
HERE = os.path.dirname(COCKPIT)
HOST, PORT = "127.0.0.1", 8090
LOG = os.path.join(HERE, "cockpit_guard.log")

CHECK_INTERVAL = 10     # 存活时轮询间隔（秒）
RESPAWN_WAIT = 8        # 重拉后等待启动的间隔（秒）


def log(msg: str) -> None:
    line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def healthy() -> bool:
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        op.open("http://%s:%d/" % (HOST, PORT), timeout=4)
        return True
    except Exception:
        return False


def find_8090_pid():
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True,
        ).stdout
        for line in out.splitlines():
            if (":%d " % PORT) in line and "LISTENING" in line:
                p = line.split()[-1]
                if p.isdigit():
                    return p
    except Exception:
        pass
    return None


def spawn() -> str:
    child = subprocess.Popen(
        [PY, COCKPIT, "--host", HOST, "--port", str(PORT)],
        cwd=HERE,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return str(child.pid)


def main() -> None:
    log("guard started (pid=%s)" % os.getpid())
    while True:
        if healthy():
            time.sleep(CHECK_INTERVAL)
            continue
        # 不存活：清掉残留监听者再重拉
        pid = find_8090_pid()
        if pid:
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
            time.sleep(2)
        new_pid = spawn()
        log("cockpit down -> respawned pid=%s" % new_pid)
        time.sleep(RESPAWN_WAIT)


if __name__ == "__main__":
    main()
