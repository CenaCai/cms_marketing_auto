#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 waterbomb /program 链路：
  A) 离线渲染：_program_body 在 Mautic 不可达时不再阻塞（秒级返回）
  B) 在线渲染：真实启动 8090 服务，GET /program/waterbomb_2026 返回 200（不挂死）
"""
import os, sys, time, json, socket, subprocess, urllib.request, urllib.error, threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cockpit

PORT = 8090
PROG_FILE = os.path.join(HERE, "output", "program_waterbomb_2026.json")


def _timed(label, fn):
    t0 = time.time()
    try:
        r = fn()
        dt = time.time() - t0
        print(f"[OK]   {label}: {dt:.2f}s -> {r if not isinstance(r,(dict,str)) else type(r).__name__}")
        return r, dt
    except Exception as e:
        dt = time.time() - t0
        print(f"[FAIL] {label}: {dt:.2f}s -> {type(e).__name__}: {e}")
        return None, dt


# ---------- Test A: 离线渲染（强制 Mautic 不可达） ----------
print("\n=== Test A: 离线渲染 _program_body（Mautic 不可达，必须秒级返回）===")
_orig = cockpit._mautic_reachable_safe
cockpit._mautic_reachable_safe = lambda env="local", timeout=5: (False, "forced-offline-for-test")
prog = json.load(open(PROG_FILE, encoding="utf-8"))
body, dt = _timed("render /program (offline)", lambda: cockpit._program_body(prog))
cockpit._mautic_reachable_safe = _orig
if body is None or dt > 12:
    print(">>> Test A 失败：离线渲染仍阻塞或异常")
    sys.exit(2)
print(">>> Test A 通过：离线渲染未阻塞（idx 走空索引分支）")


# ---------- Test B: 启动真实服务，GET /program 在线渲染 ----------
print("\n=== Test B: 启动 8090 服务，GET /program/waterbomb_2026 ===")
# 关闭可能残留的 8090 监听（TIME_WAIT 不影响新 listen）
p = subprocess.Popen([sys.executable, "cockpit.py"], cwd=HERE,
                     stdout=open(os.path.join(HERE, "_verify_fix.log"), "w"),
                     stderr=subprocess.STDOUT)
try:
    # 等待 /brief 就绪
    up = False
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/brief", timeout=2) as r:
                if r.status == 200:
                    up = True
                    break
        except Exception:
            time.sleep(0.5)
    print(f"[/brief] 就绪={up}")
    if not up:
        print(">>> Test B 失败：服务未就绪")
        sys.exit(2)

    socket.setdefaulttimeout(30)
    code = None
    def _get():
        global code
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/program/waterbomb_2026", timeout=28) as r:
                code = r.status
                data = r.read()
                return len(data)
        except urllib.error.HTTPError as e:
            code = e.code
            return 0
    size, dt = _timed("GET /program/waterbomb_2026 (live)", _get)
    print(f"[/program] HTTP={code} bytes={size}")
    if code != 200 or dt > 25:
        print(">>> Test B 失败：/program 挂死或状态码异常")
        sys.exit(2)
    print(">>> Test B 通过：/program 正常返回 200，未挂死")
finally:
    p.terminate()
    try:
        p.wait(timeout=5)
    except Exception:
        p.kill()

print("\nALL PASS")
