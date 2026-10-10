# -*- coding: utf-8 -*-
"""cockpit 8090 快速诊断：端口 / 进程陈旧 / 新旧代码指纹。

用法：C:\\Users\\cenacai\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe _diag_8090.py

回答三个问题：
  1. 8090 有没有在监听？
  2. 跑着的进程是不是「改动之前」启动的陈旧实例（改了文件但没重启）？
  3. 磁盘代码 vs 线上实际返回的 HTML，是否一致？
"""
import ctypes
import ctypes.wintypes as wt
import datetime
import os
import re
import subprocess
import urllib.request

PROJ = r"C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc\autopilot-poc"
SRC = os.path.join(PROJ, "cockpit.py")
DICT = os.path.join(PROJ, "i18n_dict.json")
PORT = 8090
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def listeners(port):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                         capture_output=True, text=True).stdout
    return [l.split()[-1] for l in out.splitlines()
            if f":{port}" in l and "LISTENING" in l]


def proc_start_time(pid):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    c, e, k, u = (wt.FILETIME(), wt.FILETIME(), wt.FILETIME(), wt.FILETIME())
    ok = k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                             ctypes.byref(k), ctypes.byref(u))
    k32.CloseHandle(h)
    if not ok:
        return None
    ts = (c.dwHighDateTime << 32) | c.dwLowDateTime
    return datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ts // 10)


print("=" * 62)
print("cockpit :8090 诊断")
print("=" * 62)

pids = listeners(PORT)
if not pids:
    print(f"[1] 端口 {PORT}: 未监听 —— 服务没在运行（需双击 start-cockpit.bat）")
else:
    print(f"[1] 端口 {PORT}: 正在监听，pid={pids}")
    # 进程启动后被加载的每一个文件都要比对：源码 + i18n 字典
    # （字典在 i18n._dict() 里惰性加载且进程内缓存，只读一次，
    #  改 json 和改 .py 一样必须重启）
    watched = [("cockpit.py", SRC), ("i18n_dict.json", DICT)]
    latest = None
    for label, path in watched:
        if not os.path.exists(path):
            continue
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        latest = mt if latest is None or mt > latest else latest
        print(f"    {label:16s} 最后修改: {mt:%Y-%m-%d %H:%M:%S}")
    if latest is None:
        latest = datetime.datetime.fromtimestamp(os.path.getmtime(SRC))
        print(f"    cockpit.py      最后修改: {latest:%Y-%m-%d %H:%M:%S}")
    for pid in pids:
        try:
            st = proc_start_time(int(pid))
        except Exception:
            st = None
        if st is None:
            print(f"    pid {pid}: 无法读取启动时间")
            continue
        stale = st < latest
        flag = "陈旧!! 需重启" if stale else "最新"
        print(f"    pid {pid}: 启动于 {st:%Y-%m-%d %H:%M:%S}  -> {flag}")
        if stale:
            print(f"      (进程比最新改动早 {latest - st}；改动未生效 —— "
                  f"Python 不热更新，且 i18n 字典进程内只加载一次)")

print()
print("[2] 线上实际返回 vs 磁盘代码")
try:
    html = OPENER.open(f"http://127.0.0.1:{PORT}/", timeout=10).read().decode("utf-8")
    live_env = 'class="env"' in html
    live_mautic = 'class="mautic"' in html
    print(f"    线上 HTML 含旧胶囊 class=env   : {live_env}")
    print(f"    线上 HTML 含新按钮 class=mautic: {live_mautic}")
    m = re.search(r'<a class="mautic"\s+href="([^"]*)"', html)
    if m:
        print(f"    线上按钮 href: {m.group(1)}")
    disk = open(SRC, encoding="utf-8").read()
    print(f"    磁盘代码含 class=mautic: {'class=\"mautic\"' in disk}")
    if live_mautic != ('class="mautic"' in disk):
        print("    => 不一致：进程陈旧，必须重启才能生效")

    # 文案指纹：切换器中文标签（i18n 字典里的 "中文" 条目）
    if os.path.exists(DICT):
        import json
        want = (json.load(open(DICT, encoding="utf-8")) or {}).get("中文")
        m2 = re.search(r'<a href="\?lang=zh"[^>]*>([^<]*)</a>', html)
        live_label = m2.group(1) if m2 else "?"
        print(f"    磁盘字典 中文 -> {want!r}   线上显示 -> {live_label!r}")
        if want and live_label != want:
            print("    => 字典改动未加载：i18n 字典进程内只读一次，必须重启")
except Exception as e:
    print(f"    无法访问 http://127.0.0.1:{PORT}/ -> {type(e).__name__}: {e}")

print()
print("提示：由 Explorer 双击 start-cockpit.bat 启动的进程可长期存活；")
print("      由 agent 工具调用拉起的会在调用结束后被回收。")