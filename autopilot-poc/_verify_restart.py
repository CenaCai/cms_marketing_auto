# -*- coding: utf-8 -*-
"""Fresh-instance verification for cockpit :8090.

Starts a brand-new cockpit.py on 8090 (port is free after the stale
pid was killed), fetches the pages, and asserts the two user-requested
changes are actually rendered by the NEW code:
  A) switcher label = "CN" (dict 中文->CN loaded)
  B) the 4 channel rows ("预留 sms/push/whatsapp", "主渠道 email") removed
Then stops the instance. Proves disk code serves correctly without
depending on the user's manual restart.
"""
import os
import sys
import time
import subprocess
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
PY = r"C:\Users\cenacai\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
PORT = 8090
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch(path, cookie=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}")
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with OP.open(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


print("[start] launching fresh cockpit.py on", PORT)
p = subprocess.Popen(
    [PY, "cockpit.py", "--port", str(PORT)],
    cwd=HERE,
    stdout=open(os.path.join(HERE, "_verify_restart.log"), "w"),
    stderr=subprocess.STDOUT,
)
print(f"[start] pid={p.pid}, waiting for readiness ...")
up = False
for _ in range(60):
    try:
        with OP.open(f"http://127.0.0.1:{PORT}/", timeout=3) as r:
            if r.status == 200:
                up = True
                break
    except Exception:
        time.sleep(0.5)
print(f"[ready] {up}")

checks = []
for path in ("/", "/brief"):
    code, html = fetch(path)
    print(f"\n=== GET {path} -> HTTP {code} (len {len(html) if isinstance(html, str) else '?'}) ===")
    if not isinstance(html, str):
        print("  fetch error:", html)
        continue
    checks.append((path, "header mautic button present", 'class="mautic"' in html))
    checks.append((path, "mautic href -> http://localhost:8080", "http://localhost:8080" in html))
    # switcher label: EN mode renders <a ...>中文</a> -> translate_html -> >CN<
    checks.append((path, "switcher label = CN (old 'Chinese' gone)", (">CN<" in html) and (">Chinese<" not in html)))
    # channel rows removed
    checks.append((path, "channel row '预留 sms' removed", "预留 sms" not in html))
    checks.append((path, "channel row '主渠道 email' removed", "主渠道 email" not in html))
    if path == "/brief":
        # placeholder 属性通道：EN 模式下举例文案应为英文
        checks.append((path, "objective placeholder EN", "placeholder='e.g. Promote tickets" in html))
        checks.append((path, "old CN objective placeholder gone", "例：为「2027" not in html))
        checks.append((path, "constraints placeholder EN", "Do not disturb 22:00-09:00" in html))
        checks.append((path, "old CN constraints placeholder gone", "免打扰" not in html))

# zh 模式回归：Cookie 指定 zh，placeholder 必须保持中文原文
code, html_zh = fetch("/brief", cookie="cockpit_lang=zh")
print(f"\n=== GET /brief (Cookie zh) -> HTTP {code} ===")
if isinstance(html_zh, str):
    checks.append(("/brief@zh", "CN objective placeholder kept", "例：为「2027" in html_zh))
    checks.append(("/brief@zh", "CN constraints placeholder kept", "免打扰" in html_zh))
    checks.append(("/brief@zh", "no EN placeholder leaked", "e.g. Promote tickets" not in html_zh))
else:
    print("  fetch error:", html_zh)

allpass = all(v for _, _, v in checks)
for path, label, ok in checks:
    print(f"  [{'PASS' if ok else 'FAIL'}] {path}: {label}")
print("\nRESULT:", "ALL PASS" if allpass else "SOME FAILED")

p.terminate()
try:
    p.wait(timeout=5)
except Exception:
    p.kill()
print("[done] fresh instance stopped.")
