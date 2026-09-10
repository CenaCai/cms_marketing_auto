# 刷新 :8090 驾驶舱（让甲A program 回来）

## 现象
- 打开 http://localhost:8090/ 显示「暂无 Program」，KPI 全是 0。
- 点 /program/jiaa_football_2050 返回「未找到」(404)。

## 根因
- 甲A 数据完好：`autopilot-poc/autopilot-poc/output/program_jiaa_football_2050.json`（4 个 campaign）。
- 但**当前运行的旧服务器**读的是**空的** `output/` 目录（项目重构后 cockpit.py 移到了两层路径 `autopilot-poc/autopilot-poc/`，旧进程内存里的 `OUT_DIR` 仍指向父层空目录）。
- cockpit.py 用 `HERE = dirname(__file__)` 推导 `OUT_DIR`，无热加载，所以必须重启且必须用「两层路径」的 cockpit.py 启动，才能落到含甲A的嵌套 `output/`。

## 已做的加固
1. `cockpit.py` 新增 `_resolve_output_dir()`：优先 `HERE/output`，若为空则向上逐级找含 `program_*.json` 的 `output/`，避免以后再因启动路径不对而读空目录。
2. `refresh_cockpit.bat` 强化：先 `taskkill /IM pythonw.exe`，再按端口 8090 兜底 `taskkill /PID`，最后用**两层路径**启动 `pythonw ...\autopilot-poc\autopilot-poc\cockpit.py`。

## 你需要做的（关键）
> 本环境的 agent 无法让启动的服务器进程跨轮次存活（沙箱会在 ~1.5 分钟内回收它 spawn 的进程），
> 所以**必须由你本机双击运行**下面的 bat 才能真正重启：

双击：`C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc\refresh_cockpit.bat`

运行后稍候刷新 http://localhost:8090/ ：
- 首页应出现「甲A」program 卡片（4 个 campaign）。
- /program/jiaa_football_2050 正常显示。

## 验证（你跑完 bat 后我可代验）
- `curl -s -o /dev/null -w '%{http_code}' http://localhost:8090/program/jiaa_football_2050` 应返回 200。
- 首页 KPI 的 Program 数应 > 0。
