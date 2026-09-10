"""cockpit 8090 自愈保活脚本（常驻后台，无窗口）。

设计要点：
- 纯后台进程：用 pythonw 运行本脚本，或由 Windows 计划任务（SYSTEM）调用，绝不弹控制台窗口。
- 自愈：检查 127.0.0.1:8090 是否在监听且返回 200；仅在「不在监听 / 不健康」时才拉起，
  已健康则直接退出（幂等，避免双实例）。
- 拉起前先 rm -rf __pycache__，规避旧字节码导致启动 NameError: name 'deque' is not defined。
- 子进程用 DETACHED_PROCESS 完全脱离父进程（计划任务/调度器回收也不影响它常驻）。
"""
import argparse
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHONW = r"C:\Users\cenacai\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
HOST, PORT = "127.0.0.1", 8090
LOG = os.path.join(HERE, "cockpit_8090.log")


def _healthy() -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _keepalive_once() -> str:
    if _healthy():
        return "healthy"
    # 先清旧字节码，避免 stale .pyc 导致启动失败
    pyc = os.path.join(HERE, "__pycache__")
    if os.path.isdir(pyc):
        try:
            import shutil
            shutil.rmtree(pyc)
        except Exception:
            pass
    # 拉起（完全脱离父进程）
    try:
        with open(LOG, "ab") as lf:
            subprocess.Popen(
                [PYTHONW, "cockpit.py", "--host", HOST, "--port", str(PORT)],
                cwd=HERE,
                stdout=lf, stderr=lf,
                close_fds=True,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
    except Exception as e:  # noqa: BLE001
        return f"start_failed:{e}"
    # 给进程一点启动时间后再校验
    for _ in range(10):
        time.sleep(1)
        if _healthy():
            return "started"
    return "start_timeout"


def _log(result: str, force: bool = False) -> None:
    # 守护模式下只在状态变化/异常时落盘，避免每分钟刷屏日志
    if result == "healthy" and not force:
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(HERE, "cockpit_keepalive.log"), "a") as f:
        f.write(f"[{ts}] keepalive -> {result}\n")


def _daemon(interval: int) -> None:
    """循环守护：每 interval 秒自检一次，仅在 8090 不健康时拉起（幂等，无双实例）。"""
    _log("daemon_start", force=True)
    while True:
        try:
            _log(_keepalive_once())
        except Exception as e:  # noqa: BLE001
            _log(f"daemon_error:{e}")
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="cockpit 8090 自愈保活")
    parser.add_argument("--daemon", action="store_true", help="循环守护模式（每 --interval 秒自检自愈）")
    parser.add_argument("--interval", type=int, default=60, help="守护模式自检间隔（秒），默认 60")
    args = parser.parse_args()

    if args.daemon:
        _daemon(args.interval)
    else:
        _log(_keepalive_once())
    sys.exit(0)
