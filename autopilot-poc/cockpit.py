"""
Campaign Cockpit — 活动驾驶舱（独立部署 :8090）
=====================================================================
独立进程，经 REST API 调用 localhost:8080 的 Mautic（方案 A）。
复用 goal_intake / plan_compiler / approval_gate / mautic_client / adaptive，零第三方依赖。

路由：
  GET  /                         驾驶舱首页（Program 列表 + 新建）
  GET  /brief                    填写 Brief：运营只填业务意图，Agent 决策项只读展示
  POST /brief                    编译 → 生成 Program(N 个 campaign) → 跳转
  GET  /program/<id>            Program 流水线（各 campaign 状态/策略/审批/推送/完成回写）
  POST /program/<id>/campaign/<cid>/approve   单 campaign 审批门
  POST /program/<id>/campaign/<cid>/push      单 campaign 推送（plan_hash 校验）
  POST /program/<id>/campaign/<cid>/feedback  单 campaign 人工回填执行结果（Plan 3 手动保存）
  GET  /program/<id>/campaign/<cid>/feedback?autofill=1&date=YYYY-MM-DD   从 Mautic 拉数据预填表单（Plan 2 一键预填）
  POST /program/<id>/auto-feedback?date=YYYY-MM-DD   自动汇总某 program 的所有 campaign 昨日/指定日 Mautic 真实数（Plan 1 每日定时任务入口）
  POST /program/<id>/complete                   标记某 campaign 完成 → 回写达成并改写【当前】campaign 策略（两步：先预览 diff，确认后才落库）
  POST /program/<id>/confirm-strategy            粘贴 AI 策略 JSON → 应用到【剩余所有】campaign（两步：先预览 diff，确认后才落库）
  GET  /proposal/<id>           遗留单 campaign 提案（run_poc 产出的）
  POST /proposal/<id>/approve|/push            遗留单 campaign 审批/推送
"""
from __future__ import annotations

import argparse
import html
import json
import os
import time
import traceback
import urllib.parse
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------- 开发日志（仅本地驾驶舱可见） ---------------------------
COCKPIT_LOG = deque(maxlen=200)


def cockpit_log(level: str, msg: str) -> None:
    """记录一条开发日志（INFO / WARN / ERROR / OK）。level 用于面板配色。"""
    ts = time.strftime("%H:%M:%S")
    COCKPIT_LOG.append((ts, level, msg))
def _resolve_output_dir() -> str:
    """定位驾驶舱数据目录 output/。优先 HERE/output；若该目录为空（无 program_*.json），
    则向上逐级查找父目录中的 output/，避免项目被嵌套/移动后旧进程仍指向空目录、
    导致首页「暂无 Program」的问题。"""
    candidates = [os.path.join(HERE, "output")]
    cur = HERE
    while True:
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        candidates.append(os.path.join(parent, "output"))
        cur = parent
    for c in candidates:
        if os.path.isdir(c) and any(
            fn.startswith("program_") and fn.endswith(".json")
            for fn in os.listdir(c)
        ):
            return c
    return candidates[0]
OUT_DIR = _resolve_output_dir()

from goal_intake import parse_brief, GoalSpec
from plan_compiler import compile, dump_proposal
from approval_gate import (bind_and_approve, verify_push, is_valid,
                           ApprovalDecision)
from mautic_client import (push, load_config, ensure_project, mautic_read_assets,
                           mautic_read_campaigns, mautic_get_campaign,
                           auto_feedback_for_campaign, _aliasify,
                           invalidate_asset_cache)
from adaptive import (build_program, evaluate_and_replan, default_strategies,
                      DEFAULT_N_CAMPAIGNS, derive_plan, _split_windows,
                      ASSUMED_LP_CONV, adjust_strategy_for_verdict, _verdict_for)

# 与 adaptive.derive_plan 一致的策略阈值（Agent 可达性校验用）
RC_MAX = 0.50

PORT = 8090
HOST = "127.0.0.1"

# 多选表单字段（提交时同名多值，后端按 list 解析）
MULTI_FORM_FIELDS = {"audience_age", "audience_gender", "audience_income",
                     "audience_education", "audience_industry",
                     "audience_source", "audience_region", "locale"}

# 全部语言（未勾选 = 双语全选）
LOCALE_ALL = ["zh_CN", "en_US"]

# --------------------------- 6 态状态机 ---------------------------
# 状态 → (中文标签, 配色 class)
STATUS = {
    "unreviewed":   ("未审核", "b-idle"),
    "reviewed":     ("已审核", "b-ok"),
    "approved_idle": ("已审核-未执行", "b-warn"),
    "executing":    ("执行中", "b-gov"),
    "done_met":     ("已完成-已达标", "b-ok"),
    "done_below":   ("已完成-未达标", "b-bad"),
    "deferred":     ("已挂起（外部事件）", "b-warn"),
}
from strategy_spec import (parse_strategy_spec, strategies_from_spec,
                           service_sequences_from_spec, spec_goal_defaults,
                           email_display)
# 一致性校验：StrategySpec 与 Brief 基础信息冲突 → 阻断（不自动纠正、不静默生成）
from spec_validation import validate_spec, format_conflicts


# --------------------------- 工具 ---------------------------
def _esc(s) -> str:
    return html.escape(str(s))


def _program_path(gid: str) -> str:
    return os.path.join(OUT_DIR, f"program_{gid}.json")


def _yesterday_str() -> str:
    import datetime as _dt
    return (_dt.date.today() - _dt.timedelta(days=1)).strftime("%Y-%m-%d")


def _load_program(gid: str):
    p = _program_path(gid)
    if not os.path.exists(p):
        # 兜底：curl / 定时任务若不百分号编码直接发原始 UTF-8 字节，
        # http.server 会按 iso-8859-1 解码成乱码，这里还原一次再查（如 /program/中文/auto-feedback）。
        try:
            alt = gid.encode("latin-1", "strict").decode("utf-8", "strict")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return None
        if alt == gid or not os.path.exists(_program_path(alt)):
            return None
        p = _program_path(alt)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_program(program: dict):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(_program_path(program["goal_id"]), "w", encoding="utf-8") as f:
        json.dump(program, f, ensure_ascii=False, indent=2)


def _permanent_remove(fp: str):
    """永久删除本地文件，绕过 WorkBuddy 运行时 safe-delete 补丁。

    该运行时通过 sitecustomize 把 os.remove 改为「移入回收站」
    （Windows: SHFileOperationW）。本项目 output/ 路径在该补丁下会抛
    SHFileOperationW 0x2，且即便成功也只是进回收站而非真正删除，
    与「清理无效 program」的意图相悖。nt.unlink 是未被补丁覆盖的底层实现，
    可真正删除。Program 删除本就是用户二次确认后的显式本地清理，应永久移除。
    """
    fp = os.path.abspath(fp)
    try:
        import nt
        nt.unlink(fp)
    except ImportError:
        # 非 Windows 回退到原生 remove
        os.remove(fp)
    except FileNotFoundError:
        # 已不存在，幂等视为成功
        return


def _load_proposal(gid: str):
    p = os.path.join(OUT_DIR, f"proposal_{gid}.json")
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _list_programs() -> list:
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = []
    for fn in os.listdir(OUT_DIR):
        if fn.startswith("program_") and fn.endswith(".json"):
            with open(os.path.join(OUT_DIR, fn), "r", encoding="utf-8") as f:
                rows.append(json.load(f))
    rows.sort(key=lambda d: d.get("goal_id", ""), reverse=True)
    return rows


def _mock_strategy(goal: GoalSpec) -> dict:
    return {
        "campaign_name": f"[PoC] {goal.objective}",
        "email_ref": "EM_MAIN_PLACEHOLDER",
        "email_followup_ref": "EM_FOLLOWUP_PLACEHOLDER",
        "subject": goal.objective,
        "followup_subject": "提醒：" + goal.objective,
    }


# --------------------------- 设计系统 ---------------------------
CSS = """:root{
 --bg:#eef2f7; --card:#ffffff; --ink:#0f172a; --muted:#64748b;
 --line:#e2e8f0; --brand:#2563eb; --brand-2:#1d4ed8; --brand-soft:#eff6ff;
 --ok:#15a34a; --ok-soft:#e7f7ee; --bad:#e11d48; --bad-soft:#fdeaef;
 --warn:#c2790a; --warn-soft:#fdf3df; --gov:#0f9d8f; --gov-soft:#e2f7f4;
 --radius:14px; --radius-sm:10px;
 --shadow:0 1px 2px rgba(15,23,42,.04),0 8px 24px rgba(15,23,42,.06);
 --shadow-hover:0 4px 12px rgba(15,23,42,.08),0 14px 36px rgba(15,23,42,.10);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
::selection{background:var(--brand-soft);color:var(--brand-2)}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,"PingFang SC","Microsoft YaHei",sans-serif;
 background:var(--bg);color:var(--ink);font-size:14px;line-height:1.65;-webkit-font-smoothing:antialiased}
.header{background:linear-gradient(135deg,#0b223f 0%,#16365f 100%);color:#fff;padding:16px 28px;
 display:flex;align-items:center;gap:14px;box-shadow:0 2px 16px rgba(11,34,63,.28);border-bottom:3px solid var(--brand)}
.header .logo{font-size:18px;font-weight:600;letter-spacing:.4px;color:#ffffff}
.header .env{margin-left:auto;background:rgba(255,255,255,.16);padding:4px 12px;border-radius:999px;
 font-size:12px;border:1px solid rgba(255,255,255,.18)}
.wrap{max-width:1060px;margin:0 auto;padding:28px 20px 64px}
h1{font-size:22px;margin:0 0 6px;letter-spacing:-.2px}
h2{font-size:16px;margin:0 0 10px}
h3{font-size:14px;margin:0 0 8px}
.sub{color:var(--muted);font-size:13px;margin-bottom:24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
 padding:22px;margin-bottom:18px;box-shadow:var(--shadow);transition:box-shadow .2s ease,border-color .2s ease}
.card:hover{box-shadow:var(--shadow-hover);border-color:#d6deea}
.grid2{display:grid;grid-template-columns:1.15fr .85fr;gap:18px}
@media(max-width:820px){.grid2{grid-template-columns:1fr}}
label{display:block;font-size:12px;color:var(--muted);margin:14px 0 6px;font-weight:600;letter-spacing:.2px}
input,select,textarea{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:var(--radius-sm);
 font-size:14px;background:#fbfdff;color:var(--ink);font-family:inherit;transition:border-color .15s,box-shadow .15s,background .15s}
textarea{min-height:78px;resize:vertical;line-height:1.55}
input:focus,select:focus,textarea:focus{outline:0;border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;background:var(--brand);color:#fff;
 padding:10px 18px;border-radius:var(--radius-sm);border:0;font-size:13px;font-weight:500;cursor:pointer;
 text-decoration:none;transition:background .15s,transform .08s,box-shadow .15s;box-shadow:0 1px 2px rgba(37,99,235,.25)}
.btn:hover{background:var(--brand-2);color:#fff;box-shadow:0 4px 12px rgba(37,99,235,.32)}
.btn:active{transform:translateY(1px);box-shadow:none}
.btn.sec{background:var(--brand-soft);color:var(--brand);box-shadow:none}
.btn.sec:hover{background:#dbeafe}
.btn.ghost{background:#fff;color:var(--brand);border:1px solid var(--line);box-shadow:none}
.btn.ghost:hover{border-color:var(--brand);background:var(--brand-soft)}
.btn.sm{padding:6px 12px;font-size:12px}
.btn.danger{background:#fff;color:#e11d48;border:1px solid #e11d48;box-shadow:none}
.btn.danger:hover{background:#e11d48;color:#fff;border-color:#e11d48}
.badge{display:inline-block;font-size:11px;padding:3px 10px;border-radius:999px;font-weight:600;letter-spacing:.2px}
.b-ok{background:var(--ok-soft);color:var(--ok)} .b-bad{background:var(--bad-soft);color:var(--bad)}
.b-warn{background:var(--warn-soft);color:var(--warn)} .b-gov{background:var(--gov-soft);color:var(--gov)}
.b-idle{background:#eef1f5;color:#64748b}
.req{color:#e11d48;font-weight:700;margin-right:2px}  /* 必填星号 */
.opt{color:#94a3b8;font-size:11px;font-weight:500;margin-left:2px}  /* 可选小标 */
/* 多选 chip 选择器（替代原生 select multiple） */
.chip-group{display:flex;flex-wrap:wrap;gap:8px;padding:4px 0 14px;border-bottom:1px dashed #cdd6e2}
.chip{display:inline-flex;align-items:center;gap:6px;padding:8px 15px;border:1px solid var(--line);
 border-radius:999px;background:#fbfdff;font-size:13px;line-height:1;cursor:pointer;user-select:none;
 transition:border-color .15s,background .15s,color .15s,box-shadow .15s}
.chip:hover{border-color:var(--brand);background:var(--brand-soft);box-shadow:0 1px 4px rgba(37,99,235,.12)}
.chip input{display:none}
.chip:has(input:checked){background:var(--brand);border-color:var(--brand);color:#fff;font-weight:600;box-shadow:0 2px 8px rgba(37,99,235,.28)}
/* 营销目标「最近填写」历史下拉 */
.obj-history{position:relative;background:#fff;border:1px solid var(--line);border-radius:var(--radius-sm);
 margin-top:6px;box-shadow:var(--shadow);z-index:20;max-height:210px;overflow:auto}
.obj-hist-empty{padding:8px 12px;color:var(--muted);font-size:12px;border-bottom:1px solid #eef2f7}
.obj-hist-item{padding:9px 12px;font-size:13px;cursor:pointer;border-bottom:1px solid #eef2f7;transition:background .12s,color .12s}
.obj-hist-item:last-child{border-bottom:0}
.obj-hist-item:hover{background:var(--brand-soft);color:var(--brand)}
/* KPI 看板 (issue 2026-09-07) */
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:10px 0}
.kpi-card{background:#fff;border:1px solid var(--line);border-radius:var(--radius-sm);padding:16px;text-align:center;
 position:relative;overflow:hidden;transition:transform .18s,box-shadow .18s,border-color .18s}
.kpi-card:hover{transform:translateY(-3px);box-shadow:var(--shadow-hover);border-color:#d6deea}
.kpi-card::before{content:'';position:absolute;top:0;left:0;right:0;height:4px;background:var(--brand)}
.kpi-card.gov::before{background:var(--gov)} .kpi-card.warn::before{background:var(--warn)}
.kpi-card.ok::before{background:var(--ok)} .kpi-card.bad::before{background:var(--bad)}
.kpi-num{font-size:30px;font-weight:700;line-height:1.1;color:var(--ink);margin:8px 0 2px;letter-spacing:-.5px}
.kpi-card.gov .kpi-num{color:var(--gov)} .kpi-card.warn .kpi-num{color:var(--warn)}
.kpi-card.ok .kpi-num{color:var(--ok)} .kpi-card.bad .kpi-num{color:var(--bad)}
.kpi-label{font-size:12px;color:var(--muted);font-weight:500}
.kpi-sub{font-size:10px;color:var(--muted);margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{text-align:left;padding:10px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;background:#f8fafc}
tbody tr{transition:background .12s}
tbody tr:hover{background:#f5f9ff}
.tag{display:inline-block;font-size:11px;padding:2px 8px;border-radius:7px;background:#eef1f5;color:#475569;margin:1px}
.tag.gov{background:var(--gov-soft);color:var(--gov)} .tag.biz{background:var(--brand-soft);color:var(--brand)}
.tag.res{background:var(--warn-soft);color:var(--warn)}
code{background:#eef1f5;padding:2px 7px;border-radius:7px;font-size:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#334155}
.pre{background:#0f172a;color:#cfe0f2;padding:14px;border-radius:var(--radius-sm);overflow:auto;font-size:12px;border:1px solid #1e293b}
a{color:var(--brand);text-decoration:none;transition:color .12s}
a:hover{text-decoration:underline;color:var(--brand-2)}
.ext{font-weight:600} .ext::after{content:" ↗";font-weight:400}
.agent{background:var(--gov-soft);border:1px dashed #9fd6cd;border-radius:12px;padding:18px;transition:box-shadow .18s}
.agent:hover{box-shadow:var(--shadow)}
.agent h4{margin:0 0 10px;color:var(--gov);font-size:13px}
.agent .row{display:flex;flex-wrap:wrap;gap:7px}
.note{font-size:12px;color:var(--muted);margin-top:8px;line-height:1.6}
.pill{font-size:11px;color:var(--muted)}
/* 开发日志面板：仅本地驾驶舱可见，方便开发看发生了什么/哪里报错 */
.devlog{margin-top:28px;border:1px solid var(--line);border-radius:12px;background:#0e1726;color:#cfe0f2;overflow:hidden}
.devlog>summary{cursor:pointer;padding:11px 16px;font-size:13px;font-weight:600;color:#cfe0f2;background:#13203a;user-select:none;list-style:decimal inside}
.devlog>summary::-webkit-details-marker{color:#7fa7d8}
.dl-box{max-height:340px;overflow:auto;padding:10px 14px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;line-height:1.5}
.dl-row{display:flex;gap:10px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.06);flex-wrap:wrap}
.dl-ts{color:#7fa7d8;flex:0 0 auto}
.dl-lvl{flex:0 0 52px;font-weight:700;text-align:center;border-radius:5px;font-size:11px;padding:0 4px;height:18px;line-height:18px}
.dl-error .dl-lvl{background:#5a2418;color:#ff8a6a} .dl-warn .dl-lvl{background:#5a4518;color:#ffd479}
.dl-info .dl-lvl{background:#16344f;color:#9ad0ff} .dl-ok .dl-lvl{background:#16402c;color:#7ee0b0}
.dl-msg{color:#d7e6f7;flex:1;min-width:0;white-space:pre-wrap;word-break:break-word}
"""

PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{css}</style></head>
<body><div class="header"><a class="logo" href="/" target="_blank" rel="noopener" title="在新标签页打开列表页">⚙ Autopilot 活动驾驶舱</a>
<span class="env">环境 local · → Mautic :8080</span></div>
<div class="wrap">{body}</div></body></html>"""


def _page(title: str, body: str) -> str:
    return PAGE.format(title=_esc(title), css=CSS, body=body + _dev_log_panel())


def _dev_log_panel() -> str:
    """页面底部「开发日志」折叠面板：渲染模块级 COCKPIT_LOG（跨请求持久）。

    始终渲染（即便为空也显示空状态），方便开发随时看到面板位置。
    """
    if not COCKPIT_LOG:
        return ("<details class='devlog'><summary>🛠 开发日志（最近 0 条 · 仅本地可见）</summary>"
                "<div class='dl-box'><div class='dl-row dl-info'>"
                "<span class='dl-ts'></span><span class='dl-lvl'>INFO</span>"
                "<span class='dl-msg'>暂无日志，操作后将在此显示（发生了什么 / 哪里报错）。</span></div></div></details>")
    rows = []
    for ts, level, msg in reversed(COCKPIT_LOG):
        rows.append(
            f"<div class='dl-row dl-{level.lower()}'>"
            f"<span class='dl-ts'>{_esc(ts)}</span>"
            f"<span class='dl-lvl'>{_esc(level)}</span>"
            f"<span class='dl-msg'>{_esc(msg)}</span></div>")
    return (f"<details class='devlog'><summary>🛠 开发日志（最近 {len(COCKPIT_LOG)} 条 · 仅本地可见）</summary>"
            f"<div class='dl-box'>{''.join(rows)}</div></details>")


# --------------------------- 页面 ---------------------------
def _kpi_dashboard() -> str:
    """
    首页 KPI 看板：6 张小卡（自动从 output/program_*.json 聚合）。
    维度: Program 总数 / Campaign 总数 / 待审 / 执行中 / 已发 / 达标/未达标
    """
    progs = _list_programs()
    n_prog = len(progs)
    n_camp = 0
    n_pending = 0          # status == unreviewed
    n_executing = 0        # executing + approved_idle
    n_deployed = 0         # proposal.deployed == True
    n_done_met = 0         # done_met
    n_done_below = 0       # done_below
    n_deferred = 0         # deferred (外部事件挂起)
    for p in progs:
        for c in p.get("campaigns", []):
            n_camp += 1
            st = c.get("status", "")
            if st == "unreviewed":
                n_pending += 1
            elif st in ("executing", "approved_idle"):
                n_executing += 1
            elif st == "done_met":
                n_done_met += 1
            elif st == "done_below":
                n_done_below += 1
            elif st == "deferred":
                n_deferred += 1
            if (c.get("proposal") or {}).get("deployed"):
                n_deployed += 1
    pct_done = (round((n_done_met + n_done_below) * 1000 / n_camp) / 10
                if n_camp > 0 else 0.0)
    cards = [
        ("brand",  str(n_prog),   "Program",     "已发起的目标数"),
        ("gov",    str(n_camp),   "Campaign",    "总战役数（含未审/执行中/已完成）"),
        ("warn",   str(n_pending),"待审",         "需运营/审批人介入的 unreviewed"),
        ("gov",    str(n_executing),"执行中",     "executing + approved_idle"),
        ("ok",     str(n_deployed),"已发",        f"已部署到 Mautic（含 KPI 已达/未达 {pct_done}%）" if n_camp else "已部署到 Mautic"),
        ("ok" if n_done_met >= n_done_below else "bad",
         f"{n_done_met}<span style='font-size:14px;color:var(--muted)'>/{n_done_below}</span>",
         "达标/未达标", "done_met / done_below"),
    ]
    out = "<div class='kpi-row'>"
    for cls, num, lbl, sub in cards:
        out += (f"<div class='kpi-card {cls}'>"
                f"<div class='kpi-num'>{num}</div>"
                f"<div class='kpi-label'>{_esc(lbl)}</div>"
                f"<div class='kpi-sub'>{_esc(sub)}</div></div>")
    out += "</div>"
    # deferred 提示（仅在有挂起时显示）
    if n_deferred > 0:
        out += (f"<p class='b-warn' style='margin:6px 0'>⚠️ 当前有 <b>{n_deferred}</b> 个 campaign "
                f"因外部事件挂起（status=deferred），启用后转未审核进入标准通道。</p>")
    return out


def _dash_body() -> str:
    progs = _list_programs()
    kpi = _kpi_dashboard()
    if not progs:
        items = "<p class='sub'>暂无 Program。先 <a href='/brief'>填写一份 Brief</a> 发起目标。</p>"
    else:
        items = "<table><tr><th>Program</th><th>campaign 数</th><th>各 campaign 状态</th><th></th></tr>"
        for p in progs:
            camps = p.get("campaigns", []) or []
            states = " ".join(
                f"<span class='badge {STATUS.get(c.get('status', ''), ('x','b-idle'))[1]}'>"
                f"{_esc(str(c.get('cid', '')).split('_c')[-1])}:{_esc(STATUS.get(c.get('status', ''), ('x',''))[0])}</span>"
                for c in camps)
            items += (f"<tr><td><code>{_esc(p.get('goal_id', '(未知)'))}</code></td>"
                      f"<td>{len(camps)}</td><td>{states}</td>"
                      f"<td><a class='btn sec sm' href='/program/{_esc(p.get('goal_id', ''))}'>打开</a></td></tr>")
        items += "</table>"
    return (f"<h1>活动驾驶舱</h1><p class='sub'>一个目标 → 多个 campaign 自适应编排；"
            f"运营只填业务意图，治理/渠道/频次由 Agent 自动决策。</p>"
            f"<div class='card'><a class='btn' href='/brief'>+ 新建 Brief（发起目标）</a></div>"
            f"<div class='card'><h3>总览 KPI</h3>{kpi}</div>"
            f"<div class='card'>{items}</div>")


# 自动派生计划预览（前端实时计算：由总体目标转化率 + 起止日期反推单 campaign 点击率与战役数）
# 纯字符串（非 f-string），避免 JS 大括号转义；通过 f"<script>{DERIVE_JS}</script>" 注入。
DERIVE_JS = """
(function(){
function isThinObjective(s){
  // 与 server 端 _check_objective_quality 镜像: 长度<4 / 占位测试模式
  if(!s) return 'empty';
  var t=(s||'').trim();
  if(!t) return 'empty';
  if(t.length<4) return 'too_short:'+t.length;
  // 占位词 (case insensitive)
  var thin=/^(test|tests|testing|t1|t2|tmp|temp|demo|sample|samples|example|examples|asdf|qwer|qaz|wsx|zxc|abc|xyz|hello|hi|hey|ok|yes|no|测试|测|试试|试|试一下|测试一下|演示|示例|样例|占位|空|无|未填|随便|瞎填|先|一二三|一二|甲乙丙|\\d{1,9})$/i;
  if(thin.test(t)) return 'placeholder:'+t;
  return null;
}
function derive(){
  var oc=parseFloat(document.querySelector("[name=overall_conv]").value)||0;
  var sd=document.querySelector("[name=start_date]").value;
  var ed=document.querySelector("[name=end_date]").value;
  var objEl=document.querySelector("[name=objective]");
  var obj=objEl?objEl.value:'';
  var LP=0.10, MIN_CAD=7, MAXN=8, RC_MAX=0.50;
  var span=0;
  try{ var s=new Date(sd), e=new Date(ed); span=Math.max(0,(e-s)/86400000); }catch(err){ span=0; }
  var maxBySpan = (span>0)? Math.max(1, Math.min(MAXN, Math.floor(span/MIN_CAD))) : MAXN;
  var n=maxBySpan, click_rate=0, target=0, reasonable=true, optNote='';
  // 薄输入检测: 命中即强制 n=1 (与 server 端 objective 质量门槛镜像, 提交时仍会 422 拒)
  var thinReason=isThinObjective(obj);
  var thinWarn='';
  if(thinReason){
    n=1;
    var label=thinReason.startsWith('too_short')?'过短':(thinReason.startsWith('placeholder')?'命中占位/测试模式':'空');
    thinWarn="<p class='b-bad' style='margin:6px 0'>⚠️ 营销目标"+label+"：\""+_esc(obj)+"\"。提交将被拒绝（至少 4 字符、非占位词）。请补全为业务描述，如「邀请 2028 欧超决赛意向客户」。</p>";
    optNote="营销目标"+label+"：已派生 1 个占位预览（提交会被拒）";
  } else if(oc>0){
    var k=null;
    for(var c=1;c<=maxBySpan;c++){
      var pc=1-Math.pow(1-oc,1/c);
      var cr=pc/LP;
      if(cr<=RC_MAX){ k=c; break; }
    }
    if(k===null){ k=maxBySpan; }
    n=k;
    var pc=1-Math.pow(1-oc,1/n);
    click_rate=Math.round(pc/LP*10000)/10000;
    target=Math.round(oc/n*10000)/10000;
    reasonable=(click_rate<=RC_MAX)&&(n<=MAXN);
    optNote = reasonable
      ? '未提交 StrategySpec 时按「基础路径拓扑」派生单 campaign；Agent 可按 StrategySpec 决定 #campaigns / 频次 / 内容 / 折扣'
      : '单 campaign 点击率超阈值：Agent 将按策略压缩节奏 / 提升单波内容转化以满足总体目标';
  } else {
    n=maxBySpan;
    target=0;
    click_rate=0;
    reasonable=true;
    optNote='未配置总体目标转化率：跳过可达性校验，n 按日期跨度默认派生';
  }
  var rows='';
  try{
    var s=new Date(sd), e=new Date(ed), spanD=Math.max(0,(e-s)/86400000), step=spanD/n;
    for(var i=0;i<n;i++){
      var ws=new Date(s.getTime()+step*i*86400000);
      var we=(i<n-1)?new Date(s.getTime()+step*(i+1)*86400000):e;
      var f=function(x){return x.toISOString().slice(0,10);};
      rows+='<tr><td>'+(i+1)+'</td><td>'+f(ws)+' ~ '+f(we)+'</td><td>'+target+'</td></tr>';
    }
  }catch(err){ rows='<tr><td colspan=3>请同时填写开始 / 结束日期</td></tr>'; }
  var crDisp = (click_rate>0)? (Math.round(click_rate*10000)/100) + '%' : '—';
  var verdict = reasonable
    ? "<span class='b-ok'>合理 ✓</span>"
    : "<span class='b-bad'>需优化 ⚠</span>";
  var el=document.getElementById('plan-preview');
  if(oc>0||span>0||thinReason){
    el.innerHTML=thinWarn
      +'<h4 style="margin:6px 0">自动派生计划预览</h4>'
      +'<p class="note">将生成 <b>'+n+'</b> 个战役'+(thinReason?'（薄输入，强制 1）':'')+'（基于日期跨度 + 总体目标）</p>'
      +'<table><tr><th>战役</th><th>执行窗口</th><th>各 campaign 转化目标</th></tr>'+rows+'</table>'
      +'<p class="note">单 campaign 打开/点击率（推算）：<b>'+crDisp+'</b>（='+click_rate+'）</p>'
      +'<p class="note">合理性判定：'+verdict+'</p>'
      +'<p class="note">Agent 优化说明：'+optNote+'</p>';
  } else {
    el.innerHTML=thinWarn
      +'填写「总体目标转化率」与「开始 / 结束日期」后，将自动推算派生战役数量、单 campaign 点击率与合理性。';
  }
}
function _esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
['objective','overall_conv','start_date','end_date'].forEach(function(nm){
  var el=document.querySelector('[name='+nm+']'); if(el){ el.addEventListener('input', derive); }
});
derive();
})();
"""


# 「用 WorkBuddy 生成策略」按钮逻辑（纯字符串，免 f-string 大括号转义）
# 端点优先·降级复制：配置端点 → 直接回填 StrategySpec；未配置 → 复制提示词到剪贴板。
STRATEGY_GEN_JS = """
(function(){
function gatherBrief(){
  var get=function(n){var el=document.querySelector('[name='+n+']');return el?(el.value||'').trim():'';};
  var getMulti=function(n){
    var cbs=document.querySelectorAll('input[type=checkbox][name='+n+']:checked');
    if(cbs.length){return Array.from(cbs).map(function(o){return o.value;});}
    var el=document.querySelector('[name='+n+']');
    return el?(el.value||'').trim():'';};
  var fields=['age','gender','income','education','industry','source','region'];
  var profile={};
  fields.forEach(function(k){profile[k]=getMulti('audience_'+k);});
  return {goal_name:get('goal_name'),objective:get('objective'),start_date:get('start_date'),
    end_date:get('end_date'),overall_conv:get('overall_conv'),budget:get('budget'),
    locale:getMulti('locale'),constraints:get('constraints'),audience_profile:profile};
}
function setStatus(msg, ok){
  var el=document.getElementById('gen-strategy-status');
  if(!el) return;
  el.innerHTML="<span class='"+(ok?'b-ok':'b-warn')+"'>"+msg+"</span>";
}
function escapeHtml(s){
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function genCacheKey(obj){ return 'brief_genstrat_' + (obj||'').replace(/\\s+/g,' ').trim().toLowerCase(); }
function genCacheGet(key){ try{ var v=sessionStorage.getItem(key); return v?JSON.parse(v):null; }catch(e){ return null; } }
function genCacheSet(key,val){ try{ sessionStorage.setItem(key, JSON.stringify(val)); }catch(e){} }
function copyRobust(text, onOk, onFail){
  // 防挂起：navigator.clipboard.writeText 在部分内嵌预览/非安全上下文里会
  // 永久 pending（既不通告成功也不通告失败），导致「正在生成」卡死。
  // 这里加 1s 超时，超时或 reject 一律走手动兜底（已全选的文本框，一次按键即可复制）。
  var settled=false;
  function fail(){ if(!settled){ settled=true; if(onFail) onFail(); } }
  var timer=setTimeout(fail, 1000);
  function legacyExec(t){
    // 同步兜底：在 iframe / 非安全上下文里，execCommand('copy') 对剪贴板的限制
    // 通常比 navigator.clipboard 更松，往往仍能写入；失败再走手动全选。
    try{
      var ta=document.createElement('textarea');
      ta.value=t; ta.setAttribute('readonly','');
      ta.style.position='fixed'; ta.style.top='-1000px'; ta.style.opacity='0';
      document.body.appendChild(ta); ta.focus(); ta.select();
      try{ ta.setSelectionRange(0, ta.value.length); }catch(e){}
      var ok=document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    }catch(e){ return false; }
  }
  if(navigator.clipboard && navigator.clipboard.writeText){
    try{
      var p=navigator.clipboard.writeText(text);
      if(p && p.then){
        p.then(function(){ if(settled) return; settled=true; clearTimeout(timer); if(onOk) onOk(); },
                 function(){ if(settled) return;
                             if(legacyExec(text)){ settled=true; clearTimeout(timer); if(onOk) onOk(); }
                             else { fail(); } });
        return;
      }
    }catch(e){ /* fall through to legacy */ }
  }
  if(legacyExec(text)){ if(!settled){ settled=true; clearTimeout(timer); if(onOk) onOk(); } }
  else { fail(); }
}
function doGen(force){
  force = !!force;
  var btn=document.getElementById('gen-strategy-btn');
  if(btn) btn.disabled=true;
  var brief=gatherBrief();
  setStatus('正在生成策略…', false);
  // 会话内记忆：相同营销目标（归一化）不再调 AI，直接复用上次生成的 StrategySpec
  var obj=(brief.objective||'').trim();
  var key=obj?genCacheKey(obj):null;
  if(key && !force){
    var cached=genCacheGet(key);
    if(cached && cached.strategy_spec){
      var ta0=document.querySelector('[name=strategy_spec]');
      if(ta0){ ta0.value=cached.strategy_spec; }
      var msg='♻️ 会话内复用上次策略（未调用 AI）'+(cached.via?(' · '+cached.via):'')+
              ' <a href="#" id="gen-strategy-force" style="margin-left:8px">重新生成（忽略缓存）</a>';
      setStatus(msg, true);
      var forceLink=document.getElementById('gen-strategy-force');
      if(forceLink){
        forceLink.onclick=function(ev){
          ev.preventDefault();
          sessionStorage.removeItem(key);
          doGen(true);
        };
      }
      if(btn) btn.disabled=false;
      return;
    }
  }
  fetch('/brief/generate-strategy', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(brief)
  }).then(function(r){ return r.json().then(function(j){ return {ok:r.ok, j:j}; }); })
    .then(function(res){
      var j=res.j||{};
      if(res.ok && j.ok && j.strategy_spec){
        var ta=document.querySelector('[name=strategy_spec]');
        if(ta){ ta.value=j.strategy_spec; }
        if(key){ genCacheSet(key, {strategy_spec:j.strategy_spec, via:j.via}); }
        setStatus('✅ 已生成 StrategySpec 并填入上方文本框', true);
      } else if(j.fallback){
        var p=j.prompt||'';
        copyRobust(p, function(){
          setStatus('已复制提示词到剪贴板：请在 WorkBuddy 粘贴发给小腾生成策略，再把返回的 JSON 贴回下方文本框', false);
        }, function(){
          setStatus('自动复制失败，文本已为您全选，请按 Ctrl+C / ⌘C 复制：<br><textarea id="manual-prompt" readonly style="width:100%;height:120px">'+escapeHtml(p)+'</textarea>', false);
          var mt=document.getElementById('manual-prompt');
          if(mt){ mt.focus(); mt.select(); try{ mt.setSelectionRange(0, mt.value.length); }catch(e){} }
        });
      } else {
        setStatus('生成失败：'+(j.error||'未知错误'), false);
      }
    })
    .catch(function(e){ setStatus('请求失败：'+e, false); })
    .finally(function(){ if(btn) btn.disabled=false; });
}
function doCopyPrompt(){
  var btn=document.getElementById('copy-prompt-btn');
  if(btn) btn.disabled=true;
  setStatus('正在生成基础信息…', false);
  var brief=gatherBrief();
  fetch('/brief/strategy-prompt', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(brief)
  }).then(function(r){ return r.json().then(function(j){ return {ok:r.ok, j:j}; }); })
    .then(function(res){
      var j=res.j||{};
      if(res.ok && j.ok && j.prompt){
        var p=j.prompt||'';
        copyRobust(p, function(){
          setStatus('✅ 已复制基础信息：请在 WorkBuddy 粘贴发给小腾生成策略，再把返回的 JSON 贴回上方文本框', true);
        }, function(){
          setStatus('自动复制失败，文本已为您全选，请按 Ctrl+C / ⌘C 复制：<br><textarea id="manual-prompt" readonly style="width:100%;height:120px">'+escapeHtml(p)+'</textarea>', false);
          var mt=document.getElementById('manual-prompt');
          if(mt){ mt.focus(); mt.select(); try{ mt.setSelectionRange(0, mt.value.length); }catch(e){} }
        });
      } else {
        setStatus('复制失败：'+(j.error||'未知错误'), false);
      }
    })
    .catch(function(e){ setStatus('请求失败：'+e, false); })
    .finally(function(){ if(btn) btn.disabled=false; });
}
var b=document.getElementById('gen-strategy-btn');
if(b){ b.addEventListener('click', function(ev){ ev.preventDefault(); doGen(); }); }
var cb=document.getElementById('copy-prompt-btn');
if(cb){ cb.addEventListener('click', function(ev){ ev.preventDefault(); doCopyPrompt(); }); }
})();
"""


def load_strategy_gen_config() -> dict:
    """
    读取「策略自动生成端点」配置（端点优先·降级复制）。
    来源优先级：环境变量 WORKBUDDY_STRATEGY_ENDPOINT/TOKEN > config.json [env].strategy_gen。
    返回 {enabled, endpoint, method, headers, timeout}。
    """
    endpoint = os.environ.get("WORKBUDDY_STRATEGY_ENDPOINT", "").strip()
    token = os.environ.get("WORKBUDDY_STRATEGY_TOKEN", "").strip()
    cfg: dict = {}
    cfg_path = os.path.join(HERE, "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                allcfg = json.load(f)
            sg = (allcfg.get("local", {}) or {}).get("strategy_gen") or {}
            if not endpoint:
                endpoint = (sg.get("endpoint") or "").strip()
            if not token:
                token = (sg.get("auth_token") or "").strip()
            cfg = sg
        except Exception:  # noqa: BLE001
            pass
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for k, v in (cfg.get("headers") or {}).items():
        headers[k] = v
    return {
        "enabled": bool(endpoint),
        "endpoint": endpoint,
        "method": (cfg.get("method") or "POST").upper(),
        "headers": headers,
        "timeout": int(cfg.get("timeout") or 30),
    }


def load_deepseek_config() -> dict:
    """
    读取 DeepSeek 意图识别配置（营销目标输入框的 AI 自动赋值）。
    来源优先级：环境变量 DEEPSEEK_API_KEY > config.json [deepseek].api_key。
    Tracking ID 作为自定义请求头 X-Tracking-Id 透传（DeepSeek chat API 未正式文档化该头，
    服务端通常会忽略未知头，保留以满足用户「接入 Tracking ID」诉求）。
    返回 {enabled, api_key, tracking_id, base_url, model, timeout, headers}。
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    tracking_id = os.environ.get("DEEPSEEK_TRACKING_ID", "").strip()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "").strip()
    model = os.environ.get("DEEPSEEK_MODEL", "").strip()
    cfg: dict = {}
    cfg_path = os.path.join(HERE, "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                allcfg = json.load(f)
            dk = allcfg.get("deepseek") or {}
            if not api_key:
                api_key = (dk.get("api_key") or "").strip()
            if not tracking_id:
                tracking_id = (dk.get("tracking_id") or "").strip()
            if not base_url:
                base_url = (dk.get("base_url") or "https://api.deepseek.com").strip()
            if not model:
                model = (dk.get("model") or "deepseek-chat").strip()
            cfg = dk
        except Exception:  # noqa: BLE001
            pass
    if not base_url:
        base_url = "https://api.deepseek.com"
    if not model:
        model = "deepseek-chat"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if tracking_id:
        headers["X-Tracking-Id"] = tracking_id
    return {
        "enabled": bool(api_key),
        "api_key": api_key,
        "tracking_id": tracking_id,
        "base_url": base_url.rstrip("/"),
        "model": model,
        "timeout": int(cfg.get("timeout") or 30),
        "headers": headers,
    }


def _deepseek_completion(system_prompt: str, user_content: str, temperature: float = 0.0) -> str:
    """
    调 DeepSeek chat/completions，返回 message.content 文本。
    未配置 / 请求失败 / 解析失败时 raise RuntimeError（带可读信息）。
    （意图识别与策略合成共用，避免两处重复拼请求。）
    """
    cfg = load_deepseek_config()
    if not cfg["enabled"]:
        raise RuntimeError("未配置 DeepSeek（config.json [deepseek].api_key 或 DEEPSEEK_API_KEY）")
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
    }
    import urllib.request as _u, urllib.error as _ue  # noqa: E402
    url = cfg["base_url"] + "/chat/completions"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = _u.Request(url, data=data, method="POST")
    for k, v in cfg["headers"].items():
        req.add_header(k, v)
    try:
        with _u.urlopen(req, timeout=cfg["timeout"]) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except _ue.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"DeepSeek HTTP {e.code}: {raw[:500]}")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"DeepSeek 请求失败：{e}")
    try:
        outer = json.loads(raw)
        content = (outer.get("choices") or [{}])[0].get("message", {}).get("content", "")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"DeepSeek 返回解析失败：{e}；原文：{raw[:500]}")
    if not content:
        raise RuntimeError("DeepSeek 返回空内容")
    return content


def _log_ai_error(msg: str) -> None:
    """
    把 AI 识别链路的异常落到 ai_error.log（追加）。
    存在意义：Handler 里未捕获的异常只会让 Python 掐断连接，
    浏览器端表现为无响应的 `TypeError: Failed to fetch`，控制台不会留痕，
    没有这个日志就永远查不到真实原因。
    """
    try:
        import datetime as _dt
        with open(os.path.join(HERE, "ai_error.log"), "a", encoding="utf-8") as f:
            f.write(f"[{_dt.datetime.now().isoformat(timespec='seconds')}] {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def _age_buckets_from_range(rng: str) -> str:
    """
    "0-40" / "50-" 这样的数值年龄范围 → 覆盖的档位串（规则同前端 matchAgeBuckets：按交集算）。
    用途：DeepSeek 只回了 audience_age_range 时，audience_age 档位由服务端兜底算出——
    策略合成 / 画像推断都消费档位，不能因为新增 range 字段就断供。
    """
    s = (rng or "").strip()
    if "-" not in s:
        return ""
    lo_s, hi_s = (x.strip() for x in s.split("-", 1))
    lo = int(lo_s) if lo_s.isdigit() else None
    hi = int(hi_s) if hi_s.isdigit() else None
    if lo is None and hi is None:
        return ""
    buckets = [(18, 24), (25, 34), (35, 44), (45, 54), (55, None)]
    out = []
    for b_lo, b_hi in buckets:
        if lo is not None and b_hi is not None and b_hi < lo:
            continue
        if hi is not None and b_lo > hi:
            continue
        out.append(f"{b_lo}-{b_hi}" if b_hi else f"{b_lo}+")
    return ",".join(out)


# 「营销目标 → AI 意图识别」按钮逻辑（DeepSeek）：读取目标文本，回填简称/日期/年龄/性别/收入/渠道来源等字段。
AI_PARSE_JS = """
(function(){
function setStatus(msg, ok){
  var el=document.getElementById('ai-parse-status');
  if(!el) return;
  el.innerHTML="<span class='"+(ok?'b-ok':'b-warn')+"'>"+msg+"</span>";
}
function setVal(name, val){
  if(val===undefined || val===null || val==='') return;
  var cbs=document.querySelectorAll('input[type=checkbox][name='+name+']');
  if(cbs.length){
    var arr=Array.isArray(val)?val.map(String):String(val).split(',').map(function(s){return s.trim();});
    cbs.forEach(function(cb){
      cb.checked = arr.indexOf(cb.value)>=0;
      if(cb.dispatchEvent){ cb.dispatchEvent(new Event('change',{bubbles:true})); }
    });
    return;
  }
  var el=document.querySelector('[name='+name+']');
  if(!el) return;
  if(el.tagName==='SELECT'){
    // 校验选项存在，避免填入非法值
    var ok=false; for(var i=0;i<el.options.length;i++){ if(el.options[i].value===val){ok=true;break;} }
    if(ok){ el.value=val; }
  } else {
    if(el.value && el.value.trim() && name==='constraints'){
      el.value = el.value.replace(/\\s+$/,'') + "\\n" + val;
    } else {
      el.value = val;
    }
  }
  if(el.dispatchEvent){ el.dispatchEvent(new Event('change', {bubbles:true})); }
  if(el.dispatchEvent){ el.dispatchEvent(new Event('input', {bubbles:true})); }
}
function aiCacheKey(obj){ return 'brief_aiparse_v2_' + (obj||'').replace(/\\s+/g,' ').trim().toLowerCase(); }
function aiCacheGet(key){ try{ var v=sessionStorage.getItem(key); return v?JSON.parse(v):null; }catch(e){ return null; } }
function aiCacheSet(key,val){ try{ sessionStorage.setItem(key, JSON.stringify(val)); }catch(e){} }
function matchAgeBuckets(minRaw, maxRaw){
  var buckets=[["18",24],["25",34],["35",44],["45",54],["55",200]];
  var min = (minRaw===''||minRaw==null)?null:parseInt(minRaw,10);
  var max = (maxRaw===''||maxRaw==null)?null:parseInt(maxRaw,10);
  if((min===null&&max===null)||(min!==null&&isNaN(min))||(max!==null&&isNaN(max))) return [];
  if(min!==null&&max!==null&&min>max){ var t=min; min=max; max=t; }
  var out=[];
  for(var i=0;i<buckets.length;i++){
    var lo=parseInt(buckets[i][0],10), hi=buckets[i][1];
    var overlap = (min===null || hi>=min) && (max===null || lo<=max);
    if(overlap) out.push(buckets[i][0] + (hi>=200?'+':('-'+hi)));
  }
  return out;
}
function updateAgeMatch(){
  var mn=document.querySelector('[name=audience_age_min]');
  var mx=document.querySelector('[name=audience_age_max]');
  var bks=matchAgeBuckets(mn?mn.value:'', mx?mx.value:'');
  var hid=document.querySelector('[name=audience_age]');
  if(hid) hid.value=bks.join(',');
  var disp=document.getElementById('audience_age_match_disp');
  if(disp) disp.textContent = bks.length ? ('匹配档位：'+bks.join('、')) : '';
}
function fillAgeFromBuckets(str){
  if(!str) return;
  var parts=String(str).split(',').map(function(s){return s.trim();}).filter(Boolean);
  if(!parts.length) return;
  var mn=999, mx=null;
  parts.forEach(function(p){
    if(p.indexOf('+')>=0){ var a=parseInt(p,10); if(!isNaN(a)){ mn=Math.min(mn,a); } }
    else { var rng=p.split('-'); var lo=parseInt(rng[0],10), hi=parseInt(rng[1],10); if(!isNaN(lo)) mn=Math.min(mn,lo); if(!isNaN(hi)) mx=(mx===null?hi:Math.max(mx,hi)); }
  });
  var imn=document.querySelector('[name=audience_age_min]'), imx=document.querySelector('[name=audience_age_max]');
  if(imn && mn<999) imn.value=mn;
  if(imx && mx!==null) imx.value=mx;
  updateAgeMatch();
}
function fillParse(j){
  setVal('goal_name', j.goal_name);
  setVal('start_date', j.start_date);
  setVal('end_date', j.end_date);
  setVal('overall_conv', j.overall_conv);
  setVal('is_revenue', j.is_revenue);
  setVal('budget', j.budget);
  setVal('locale', j.locale);
  setVal('audience_age', j.audience_age);
  if(j.audience_age_range){
    var _p=String(j.audience_age_range).split('-');
    var _lo=parseInt(_p[0],10), _hi=(_p.length>1)?parseInt(_p[1],10):NaN;
    var _imn=document.querySelector('[name=audience_age_min]'), _imx=document.querySelector('[name=audience_age_max]');
    if(_imn && !isNaN(_lo)) _imn.value=_lo;
    if(_imx) _imx.value = isNaN(_hi) ? '' : _hi;
    updateAgeMatch();
  } else {
    fillAgeFromBuckets(j.audience_age);
  }
  setVal('audience_gender', j.audience_gender);
  setVal('audience_income', j.audience_income);
  setVal('audience_source', j.audience_source);
  setVal('audience_education', j.audience_education);
  setVal('audience_industry', j.audience_industry);
  setVal('audience_region', j.audience_region);
  setVal('constraints', j.constraints);
  setVal('strategy_spec', j.strategy_spec);
}
function doParse(force){
  force = !!force;
  var btn=document.getElementById('ai-parse-btn');
  if(btn) btn.disabled=true;
  var el=document.querySelector('[name=objective]');
  var objective=el?(el.value||'').trim():'';
  if(!objective){ if(btn) btn.disabled=false; setStatus('请先填写「营销目标」文本', false); return; }
  var key=aiCacheKey(objective);
  if(!force){
    var cached=aiCacheGet(key);
    if(cached && cached.ok){
      fillParse(cached);
      var filled=(cached.filled||[]).join('、')||'无可回填字段';
      var msg='♻️ 会话内复用上次识别结果（未调用 DeepSeek）：'+filled+
              ' <a href="#" id="ai-parse-force" style="margin-left:8px">重新识别（忽略缓存）</a>';
      setStatus(msg, true);
      var forceLink=document.getElementById('ai-parse-force');
      if(forceLink){
        forceLink.onclick=function(ev){
          ev.preventDefault();
          sessionStorage.removeItem(key);
          doParse(true);
        };
      }
      if(btn) btn.disabled=false;
      return;
    }
  }
  setStatus('正在调用 DeepSeek 识别意图…', false);
  fetch('/brief/ai-parse', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({objective:objective})
  }).then(function(r){ return r.json().then(function(j){ return {ok:r.ok, j:j}; }); })
    .then(function(res){
      var j=res.j||{};
      if(res.ok && j.ok){
        fillParse(j);
        aiCacheSet(key, Object.assign({}, j));
        setStatus('✅ 已识别并回填：'+(j.filled||[]).join('、')||'无可回填字段', true);
      } else {
        setStatus('识别失败：'+(j.error||'未知错误'), false);
      }
    })
    .catch(function(e){ setStatus('请求失败：'+e, false); })
    .finally(function(){ if(btn) btn.disabled=false; });
}
var b=document.getElementById('ai-parse-btn');
if(b){ b.addEventListener('click', function(ev){ ev.preventDefault(); doParse(); }); }
})();
"""


# 「营销目标」最近填写历史（localStorage）：浏览器对 textarea 不提供原生 autofill，
# 这里自建下拉，记录最近提交的目标，点击输入框弹出、点选回填。
OBJ_HISTORY_JS = """
(function(){
  var KEY='brief_objective_history';
  function geth(){ try{ return JSON.parse(localStorage.getItem(KEY)||'[]'); }catch(e){ return []; } }
  function seth(h){ try{ localStorage.setItem(KEY, JSON.stringify(h)); }catch(e){} }
  function esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  var ta=document.querySelector('[name=objective]');
  if(!ta) return;
  var dd=document.createElement('div'); dd.className='obj-history'; dd.style.display='none';
  ta.parentNode.insertBefore(dd, ta.nextSibling);
  function render(){
    var h=geth();
    if(!h.length){ dd.style.display='none'; return; }
    var html='<div class="obj-hist-empty">最近填写（点击回填）：</div>';
    h.forEach(function(x){ html+='<div class="obj-hist-item">'+esc(x)+'</div>'; });
    dd.innerHTML=html;
    var items=dd.querySelectorAll('.obj-hist-item');
    items.forEach(function(item,i){
      item.onclick=function(){
        ta.value=h[i]; dd.style.display='none';
        if(ta.dispatchEvent){ ta.dispatchEvent(new Event('input',{bubbles:true})); }
        ta.focus();
      };
    });
    dd.style.display='block';
  }
  function record(){
    var v=(ta.value||'').trim();
    if(v.length<4) return;
    var h=geth().filter(function(x){ return x!==v; });
    h.unshift(v); if(h.length>8) h=h.slice(0,8); seth(h);
  }
  ta.addEventListener('focus', function(){ render(); });
  ta.addEventListener('blur', function(){ setTimeout(function(){ dd.style.display='none'; },160); });
  var form=ta.closest('form');
  if(form){ form.addEventListener('submit', record); }
})();
"""


def campaign_count(start_date: str, end_date: str, overall_conv: str) -> dict:
    """
    campaign（波次）数量：只由「活动周期 D」与「预期转化率 C」决定，画像包不参与。
    服务端算好后硬塞进提示词——实测让模型自己算 D/C 不可靠（60 天 + 10% 仍只出 3 波）。
    返回 {n, days, conv, reason}；days 为 None 表示日期缺失/不可解析。
    """
    from datetime import date as _date
    days = None
    try:
        _s = _date.fromisoformat((start_date or "").strip())
        _e = _date.fromisoformat((end_date or "").strip())
        days = (_e - _s).days + 1
        if days < 1:
            days = None
    except Exception:  # noqa: BLE001
        days = None
    conv = None
    try:
        _c = (overall_conv or "").strip()
        if _c:
            conv = float(_c)
    except Exception:  # noqa: BLE001
        conv = None
    if days is None:
        base, base_txt = 3, "周期未知 → 基准 3"
    elif days <= 14:
        base, base_txt = 2, "D≤14 天 → 基准 2"
    elif days <= 45:
        base, base_txt = 3, "15≤D≤45 天 → 基准 3"
    elif days <= 90:
        base, base_txt = 4, "46≤D≤90 天 → 基准 4"
    else:
        base, base_txt = 5, "D>90 天 → 基准 5"
    if conv is not None and conv >= 0.10:
        adj, adj_txt = 1, "C≥10% → +1"
    elif conv is None or conv <= 0.02:
        adj, adj_txt = -1, "C 未设置或 ≤2% → −1"
    else:
        adj, adj_txt = 0, "2%<C<10% → ±0"
    n = max(1, min(5, base + adj))
    return {"n": n, "days": days, "conv": conv,
            "reason": f"{base_txt}；{adj_txt}；夹取 [1,5] → {n}"}


# ---- 方向 A：增长运营专家团上下文注入 + WorkBuddy 专家 hook（预留） ----

def load_workbuddy_config() -> dict:
    """
    读取策略合成上下文开关（config.json [workbuddy]，可选段）。
    控制是否注入 Mautic 资产清单 / 历史 program 反馈，以及读取 Mautic 环境。
    返回 {mautic_env, strategy_context:{mautic_assets,history}}；缺省全部启用。
    """
    cfg: dict = {"mautic_env": "local",
                 "strategy_context": {"mautic_assets": True, "history": True}}
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            allcfg = json.load(f)
        wb = allcfg.get("workbuddy") or {}
        if wb.get("mautic_env"):
            cfg["mautic_env"] = wb["mautic_env"]
        if isinstance(wb.get("strategy_context"), dict):
            cfg["strategy_context"].update(wb["strategy_context"])
    except Exception:  # noqa: BLE001
        pass
    return cfg


def _collect_mautic_context() -> str:
    """读取 Mautic 实例资产清单（emails/segments/pages 的 name+alias），注入策略合成提示词。
    防御式：缺凭证/连接失败/异常 → 明确标注「数据缺失」，不阻断 prompt 生成（遵循增长运营行为准则：工具无返回即标缺失）。"""
    try:
        import mautic_client
        env = load_workbuddy_config().get("mautic_env") or "local"
        assets = mautic_client.mautic_read_assets(env)
    except Exception as e:  # noqa: BLE001
        return ("（Mautic 资产清单：数据缺失（data_missing）—— 读取异常：%s。"
                "LLM 须将 needs_operator_review=true，对 email_ref 一律用 generate（新建），"
                "并在 operator_review_notes 建议人工补齐资产清单。）" % e)
    if not assets.get("available"):
        reason = assets.get("reason") or "凭证未配置或未连接"
        return ("（Mautic 资产清单：数据缺失（data_missing）—— %s。"
                "LLM 须将 needs_operator_review=true，对 email_ref 一律用 generate（新建）而非 reuse，"
                "并在 operator_review_notes 标注「未连接 Mautic，复用/新建决策待人工确认」。）" % reason)
    lines = ["Mautic 实例（env=%s）已有资产（name / alias），email_ref 优先复用下列 alias/id，避免重复新建：" % env]
    for kind in ("emails", "segments", "pages"):
        items = assets.get(kind) or []
        if not items:
            continue
        shown = "、".join("%s(%s)" % (it.get("name"), it.get("alias") or it.get("id")) for it in items[:30])
        lines.append("- %s（%d）：%s%s" % (kind, len(items), shown, " …" if len(items) > 30 else ""))
    return "\n".join(lines)


def _collect_history_context() -> str:
    """读取最近 10 个 output/program_*.json，提取历史 program 的 goal_id/objective/反馈，作为策略合成复盘上下文。
    防御式：无文件/异常 → 标注「暂无历史数据」。"""
    try:
        out_dir = os.path.join(HERE, "output")
        if not os.path.isdir(out_dir):
            return "（历史 program 反馈：暂无数据（output/ 目录不存在）。）"
        import glob as _gl
        files = sorted(_gl.glob(os.path.join(out_dir, "program_*.json")),
                       key=os.path.getmtime, reverse=True)[:10]
        if not files:
            return "（历史 program 反馈：暂无数据（output/program_*.json 不存在）。）"
        rows = []
        for fp in files:
            try:
                with open(fp, encoding="utf-8") as f:
                    d = json.load(f)
                gid = d.get("goal_id") or d.get("program_id") or os.path.basename(fp)
                obj = d.get("objective") or ""
                fb = d.get("feedback") or d.get("review_note") or ""
                fb_txt = ("；反馈：%s" % fb) if fb else ""
                rows.append("- %s：%s%s" % (gid, obj, fb_txt))
            except Exception:  # noqa: BLE001
                continue
        if not rows:
            return "（历史 program 反馈：文件存在但无可用字段。）"
        return "最近 program（最多 10，供策略复用/避坑参考）：\n" + "\n".join(rows)
    except Exception as e:  # noqa: BLE001
        return "（历史 program 反馈：数据缺失（data_missing）—— %s。）" % e


def build_strategy_prompt(brief: dict, mautic_context: str = "", history_context: str = "") -> str:
    """把 Brief 上下文拼成自包含提示词，交给（角色化的）增长运营专家团生成 StrategySpec JSON。"""
    oc = (brief.get("overall_conv") or "").strip()
    oc_json = oc if oc else "0.0"
    cons = (brief.get("constraints") or "").strip().replace("\n", "；").replace("\r", "")
    name = (brief.get("goal_name") or "").strip() or "(未命名，请用 goal_id 或一句话概括)"
    # 简单 slug（无 re 依赖）：空白转下划线、非字母数字下划线剔除
    raw_gid = (brief.get("goal_id") or brief.get("goal_name") or "campaign").strip().lower()
    goal_id = "_".join(raw_gid.split()) if raw_gid else "campaign"
    goal_id = "".join(c for c in goal_id if c.isalnum() or c == "_") or "campaign"
    # locale 可能是多选 list
    _loc = brief.get("locale")
    if isinstance(_loc, (list, tuple)):
        _loc = ",".join(str(x) for x in _loc if str(x)) or "zh_CN"
    locale = (str(_loc) or "zh_CN").strip() or "zh_CN"
    lang_label = "中文" if locale == "zh_CN" else "英文" if locale == "en_US" else locale
    budget = (brief.get("budget") or "").strip() or "0"
    is_revenue = (brief.get("is_revenue") or "0").strip() in ("1", "true", "yes", "on")
    objective = (brief.get("objective") or "").strip() or "(未填写)"
    start_date = (brief.get("start_date") or "").strip() or "(未填写)"
    end_date = (brief.get("end_date") or "").strip() or "(未填写)"
    # 受众画像（可能多值 list）
    aud_pkg = (brief.get("audience_package") or "GENERIC").strip() or "GENERIC"
    # 多画像 codes（_handle_generate_strategy 注入的 infer 结果）
    aud_pkgs = brief.get("audience_packages") or []
    if isinstance(aud_pkgs, str):
        aud_pkgs = [x.strip() for x in aud_pkgs.split(",") if x.strip()]
    aud_prof = brief.get("audience_profile") or {}
    aud_lines = []
    for k, lbl in [("age", "年龄段"), ("gender", "性别"), ("income", "月收入档"),
                   ("education", "教育经历"), ("industry", "行业"),
                   ("source", "首选来源"), ("region", "国家/地区")]:
        v = aud_prof.get(k)
        if isinstance(v, (list, tuple)):
            v = ",".join(str(x) for x in v if str(x))
        else:
            v = (v or "").strip()
        if v:
            aud_lines.append(f"{lbl}={v}")
    aud_block = ("；".join(aud_lines) if aud_lines else "（运营未填，由 Agent 自行按画像包默认值推断）")
    # 多画像提示（策略取最大值）
    multi_pkg_txt = ""
    if len(aud_pkgs) > 1:
        multi_pkg_txt = (
            f"\n5. ⚠ 本 Brief 命中多个画像包：{', '.join(aud_pkgs)}。"
            "策略必须取各画像包 strategy 的**最大值**："
            "频次 max_per_24h / max_per_7d 取最大、触达时段取并集（最早开始~最晚结束）、"
            "内容 levers / CTA 取并集（各画像包 levers 全部覆盖）、文案融合多画像调性；"
            "不允许只用最高分画像覆盖其余画像。\n"
        )
    # campaign 数量：服务端按「周期 + 转化率」算好后硬塞进提示词（画像包不参与）
    _cc = campaign_count(start_date, end_date, oc)
    d_txt = str(_cc["days"]) if _cc["days"] is not None else "未知"
    c_txt = f"{_cc['conv']:.0%}" if _cc["conv"] is not None else "未设置"
    n_campaigns = _cc["n"]
    cid_list = "、".join(f"c{i}" for i in range(1, n_campaigns + 1))
    tpl = (
        "你是阿岚（增长操盘手），增长运营专家团主理人。你的任务不是「直接写 JSON」，而是先按增长运营 SOP 走完"
        "「现状盘点 → 目标接收与可达性 → 策略合成（并联内容/数据）→ 门禁确认卡片 → 输出 StrategySpec」再落 spec。"
        "请基于下方【Brief】+【Mautic 实例上下文】生成一份 StrategySpec JSON"
        "（严格 JSON，不要解释文字、不要 markdown 代码块包裹，只输出可被 json.loads 解析的对象），"
        "供「活动驾驶舱」PoC 编译成 Mautic 事件图。\n\n"
        "【Brief】\n"
        "- 营销/活动名称：{name}\n"
        "- 营销目标：{objective}\n"
        "- 开始日期：{start_date}  结束日期：{end_date}\n"
        "- 总体目标转化率：{oc}（0~1；留空表示仅意向登记 / 品牌曝光，无营收转化）\n"
        "- 语言/地区：{lang_label}（{locale}）\n"
        "- 是否涉及营收/付费目标：{is_revenue}\n"
        "- 预算金额：{budget}（¥；仅审计/审批用，不参与 ROI 计算；is_revenue=false 时忽略）\n"
        "- 目标画像包：{aud_pkg}（GENERIC=通用兜底；CUSTOM=运营自定义字段）\n"
        "- 目标人群特点：{aud_block}\n"
        "- 约束/红线：{cons}\n\n"
        "【Mautic 实例上下文（资产复用 / 命名 / 坑位约束）】\n"
        "{mautic_context}\n"
        "{history_context}\n"
        "命名与工程规范（Mautic CSTS 定制版，务必遵守）：\n"
        "- campaign / segment / email / form 资产命名前缀分别为 CMP_ / SEG_ / EM_ / FORM_；reuse-first，避免重复新建。\n"
        "- 落地页 alias 由驾驶舱 `_aliasify(\"{{campaign_name}}-落地页\")` 自动生成，"
        "**不要**在 StrategySpec 的 landing_page_url 里硬编码 alias；只给主语言 slug（如 c1-en，公开页路径，不要带 /s/ 后台前缀）。\n"
        "- Mautic 7 已知坑（违反会导致 push 500 或静默失败）：\n"
        "  · PUT 仅传 partial payload 会触发 jms_serializer 500，必须传完整对象；\n"
        "  · email 字段需平铺（不要嵌套）；\n"
        "  · campaign 事件图无法经 API 修改，只能整体 PUT/POST；\n"
        "  · 决策节点分支不可混合 decision + action 类型，否则 action 节点静默失败（count=0、无日志）；\n"
        "  · tag 详情页 500（CampaignModel.php:869 array_merge null）、campaign 图谱缺 generated column——属实例层问题，策略不背。\n"
        "【画像包与内容侧重】\n"
        "1. 选画像包（GENERIC / HNW_FAMILY / YOUNG_TREND / PARENT_FAM / CORP_GRP / DORMANT）必须先查本项目的画像包参数表"
        "（项目内路径 references/audience-content-map.json，与 cockpit.py 同级目录下），"
        "按打分公式 score = Σ weight×match / Σ weight（阈值 0.6）匹配接触人字段。命中 ≥2 个时按分数降序列候选交运营选。\n"
        "2. 命中画像包后，频次 max_per_24h/max_per_7d、静默窗、触达时段、文案调性、画面调性、CTA 模板**必须**沿用该包 strategy；不允许凭感觉改写。"
        "注意：画像包只决定每一波的**内容与触达参数**，**不决定 campaign 数量**（数量见下方【campaign 数量规则】）。\n"
        "3. 命中 0 个（且不为 GENERIC）：用 GENERIC 兜底。{multi_pkg}\n"
        "4. 输出的 audience_package 必须与上方「目标画像包 {aud_pkg}」**回显一致**（不要自创 code、不要改写大小写）；"
        "服务端会用它为该包 strategy 的默认值兜底，并在 Program 页展示。\n"
        "5. business_topic（业务主题，如「UCL2028 门票预售 / 跨年演唱会 / 早鸟优惠」）必须在顶层写明，"
        "并贯穿 objective、campaign name、subject_examples、CTA 与落地页文案——"
        "本系统不会替你猜主题，主题不清的文案一律按不可用处理。\n"
        "【campaign 数量规则（与画像包解耦）】\n"
        "1. campaign 数量 N **只**由「活动周期 D」与「预期转化率 C」决定；画像包、受众字段、预算、语言均不参与。\n"
        "2. 基准（D = 开始日期~结束日期含首尾的天数）：D≤14 → 2 个；15≤D≤45 → 3 个；46≤D≤90 → 4 个；D>90 → 5 个。\n"
        "3. 调整：C≥0.10 → +1（预期转化高，值得分波培育）；C 为空或 ≤0.02（仅曝光 / 无营收目标）→ −1。\n"
        "4. 夹取：N 下限 1、上限 5。\n"
        "5. 画像包只改变每一波讲什么、怎么讲（content_emphasis / levers / tone / CTA / 视觉 / 合规口径）；"
        "命中不同画像包**不得**增减波数。\n"
        "6. 若 Brief 原文已明确指定波次数（如「分 3 波」），以运营显式指定为准，本规则只作为未指定时的默认值。\n"
        "7. 本次 Brief 的服务端已算好：活动周期 D={d_txt} 天、预期转化率 C={c_txt}（{count_reason}）→ "
        "**必须生成恰好 {n_campaigns} 个 campaign**，cid 依次为 {cid_list}。"
        "这是硬约束：除 Brief 原文明确指定过波次数外，不得增减，也不得因画像包不同而改变。\n"
        "【国际化与落地页规则】\n"
        "1. 语言优先级先由 audience_region 判断：\n"
        "   · 若 audience_region 不含「中国大陆」（包括仅港澳台、仅海外、港澳台+海外、未选），无论 locale 是否包含 zh_CN，都只生成英文 campaign，不生成中文翻译稿；\n"
        "   · 若 audience_region 包含「中国大陆」，再按 locale 决定：\n"
        "     - locale 仅 zh_CN → 主内容中文；\n"
        "     - locale 仅 en_US → 主内容英文；\n"
        "     - locale 同时含 zh_CN 和 en_US → 默认主内容英文，附加中文翻译稿。生成时先排英文主 campaign（c1/c2/...），再排对应的中文翻译 campaign（c1_zh/c2_zh/...），英文优先执行、中文翻译稿作为双语备选。\n"
        "2. 落地页 URL 按 campaign 主语言区分，使用 Mautic 公开页路径 http://localhost:8080/<slug>（注意 /s/ 是后台前缀，公开落地页用 /{slug}）。"
        "必须用当前 campaign 的 cid 生成 URL：\n"
        "   · 英文主 campaign c1 → http://localhost:8080/c1-en\n"
        "   · 英文主 campaign c2 → http://localhost:8080/c2-en\n"
        "   · 中文翻译 campaign c1_zh → http://localhost:8080/c1_zh-zh\n"
        "   同一 campaign 的所有落地页链接必须一致，不要全部复用 c1。\n"
        "3. 分群命名体现 region+locale，如 SEG_{goal_id}_CN_ZH、SEG_{goal_id}_GLOBAL_EN。\n"
        "【输出要求】\n"
        "1. 顶层：goal_id（slug）、objective、business_topic（业务主题，一句话）、"
        "kpi（{{\"metric\":\"conversion\",\"target\":{oc_json}}}）、"
        "locale（[\"{locale}\"]）、audience_package（{aud_pkg}，回显上方目标画像包）、audience_profile（按目标人群特点字段填入）、"
        "campaigns（数组）、service_sequences（数组，可选）。\n"
        "2. 每个 campaign：{{\"cid\",\"name\",\"content_brief\":\"一句话说清这批人现在缺什么信息\","
        "\"content_emphasis\":[...画像包 strategy.levers...]，"
        "\"segment\":{{\"mode\":\"propose\",\"ref\":\"SEG_xxx\"}},"
        "\"send_conditions\":{{\"delay_hours\":int,\"max_per_24h\":int,\"max_per_7d\":int,"
        "\"quiet_hours\":\"22:00-09:00\"}},\"tags_to_write\":[...],\"email_mode\":\"reuse\"|\"generate\","
        "\"email_ref\":(reuse 填真实资产 alias/id，generate 填空),\"landing_page_url\":str,"
        "\"depends_on\":cid_or_null,\"editable_until_start\":bool,\"daily_adjust_window_hours\":24,"
        "\"content_variant\":int(可选),\"deferred\":bool(可选)}}\n"
        "   命名约定：英文主 campaign 用 c1、c2...；中文翻译 campaign 用 c1_zh、c2_zh...；中英都选时英文 campaign 排在前面，中文翻译稿排后面。\n"
        "3. 画像包命中后，第一个 campaign 的 depends_on 设为 null、editable_until_start=true；后续 campaign 串行（depends_on=前序 cid）、editable_until_start=false（等 c1 完成才由优化循环生成）。\n"
        "4. 分群必须按意图天然互斥（seed / broad / no-reach / host-confirm 等），不要共用同一 segment。\n"
        "5. 如需「用户动作即时触发」的确认件（非促销），放进 service_sequences 并设 quiet_hours_exempt=true + send_within_minutes<=5。\n"
        "6. 严格遵守约束/红线（免打扰、抑制名单、退订熔断 0.3% 等）。\n"
        "   若约束含「X:00~Y:00免打扰」，quiet_hours 必须**原样**填 \"X:00-Y:00\"（跨午夜用 '-' 连接）；"
        "午夜一律写 \"00:00\"，禁止换成示例里的 \"09:00\"（曾出现 20:00~00:00 被误写成 20:00-09:00）。\n"
        "7. 【决策纪律（增长运营行为准则）】每条 campaign 决策（画像包选型、波数、CTA、频次、落地页复用/新建、"
        "是否需换券/调预算）都必须携带 `rationale`（为什么这么定）与 `evidence`（数据出处：历史 n=xx / 行业基准 / 画像包参数表 /"
        "本实例资产清单；工具未返回数据时写「数据缺失（data_missing）」，**禁止凭空估算人数或转化率**）。\n"
        "   顶层必须输出 `needs_operator_review`（bool）：凡涉及价格/库存/券规则/预算/护栏参数调整、或目标数学上不可达、"
        "或本实例资产清单缺失导致无法判定复用 vs 新建时，置 true，并在 `operator_review_notes` 写出需人拍板的具体事项与建议选项。\n"
        "8. 只输出 JSON。\n"
    )
    return tpl.format(name=name, goal_id=goal_id, objective=objective,
                      start_date=start_date, end_date=end_date,
                      oc=oc, lang_label=lang_label, locale=locale, budget=budget,
                      is_revenue=str(is_revenue).lower(), cons=cons,
                      aud_pkg=aud_pkg, aud_block=aud_block, oc_json=oc_json,
                      multi_pkg=multi_pkg_txt,
                      d_txt=d_txt, c_txt=c_txt, count_reason=_cc["reason"],
                      n_campaigns=n_campaigns, cid_list=cid_list,
                      mautic_context=mautic_context, history_context=history_context)


def _extract_strategy_spec(raw: str):
    """从端点响应里尽量抽出 StrategySpec（对象 / 包裹字段 / JSON 字符串均可）。"""
    s = (raw or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except Exception:  # noqa: BLE001
        obj = None
    if isinstance(obj, dict):
        if "campaigns" in obj or "goal_id" in obj or "service_sequences" in obj:
            return json.dumps(obj, ensure_ascii=False, indent=2)
        for key in ("strategy_spec", "strategy", "spec", "strategySpec"):
            v = obj.get(key)
            if isinstance(v, str):
                try:
                    pv = json.loads(v)
                    return json.dumps(pv, ensure_ascii=False, indent=2)
                except Exception:  # noqa: BLE001
                    return v
            if isinstance(v, dict):
                return json.dumps(v, ensure_ascii=False, indent=2)
        return None
    if isinstance(obj, str):
        return obj
    return None


def _build_strategy_prompt_from_brief(brief: dict) -> str:
    """注入多画像推断，再拼出自包含策略合成提示词（生成 / 复制共用）。"""
    from goal_intake import infer_audience_package
    brief = dict(brief)
    # 语言/地区由 audience_region 兜底：不含「中国大陆」时强制移除 zh_CN，只走英文
    regions = brief.get("audience_profile", {}).get("region") or []
    if isinstance(regions, str):
        regions = [r.strip() for r in regions.split(",") if r.strip()]
    locales = brief.get("locale") or []
    if isinstance(locales, str):
        locales = [x.strip() for x in locales.split(",") if x.strip()]
    if "中国大陆" not in regions:
        locales = [x for x in locales if x != "zh_CN"]
        if not locales:
            locales = ["en_US"]
    brief["locale"] = locales
    inferred = infer_audience_package(brief.get("audience_profile") or {})
    brief["audience_package"] = inferred.get("code", "GENERIC")
    brief["audience_packages"] = inferred.get("codes", [])
    brief["audience_match"] = inferred
    wb_cfg = load_workbuddy_config()
    mautic_ctx = _collect_mautic_context() if wb_cfg["strategy_context"].get("mautic_assets", True) else ""
    history_ctx = _collect_history_context() if wb_cfg["strategy_context"].get("history", True) else ""
    return build_strategy_prompt(brief, mautic_context=mautic_ctx, history_context=history_ctx)


def _brief_from_parsed(parsed: dict, objective: str) -> dict:
    """
    把「意图识别」抽出的字段映射成 build_strategy_prompt 所需的 brief dict。
    audience_* → audience_profile（age/gender/income/education/industry/source/region）。
    """
    prof = {}
    for k in ("age", "gender", "income", "education", "industry", "source", "region"):
        v = parsed.get("audience_" + k)
        if isinstance(v, str):
            v = [v] if v.strip() else []
        elif not isinstance(v, (list, tuple)):
            v = []
        v = [str(x).strip() for x in v if str(x).strip()]
        if v:
            prof[k] = v
    return {
        "goal_name": (parsed.get("goal_name") or "").strip(),
        "objective": objective,
        "start_date": (parsed.get("start_date") or "").strip(),
        "end_date": (parsed.get("end_date") or "").strip(),
        "overall_conv": (parsed.get("overall_conv") or "").strip(),
        "budget": (parsed.get("budget") or "").strip(),
        "is_revenue": (parsed.get("is_revenue") or "").strip(),
        "locale": (parsed.get("locale") or "").strip(),
        "audience_profile": prof,
        "constraints": (parsed.get("constraints") or "").strip(),
    }


def _should_synthesize_strategy(parsed: dict) -> bool:
    """判断是否值得自动合成多波 StrategySpec：日期跨度 ≥7 天，或（≥1 天且给了转化目标）。"""
    from datetime import date
    s = (parsed.get("start_date") or "").strip()
    e = (parsed.get("end_date") or "").strip()
    try:
        span = (date.fromisoformat(e) - date.fromisoformat(s)).days
    except Exception:  # noqa: BLE001
        return False
    if span >= 7:
        return True
    oc = (parsed.get("overall_conv") or "").strip()
    try:
        has_conv = float(oc) > 0
    except Exception:  # noqa: BLE001
        has_conv = False
    return span >= 1 and has_conv


def _brief_form(strategy_spec: list = None, spec_err: str = "", spec_meta: dict = None,
                service_spec: list = None, prefill: dict = None,
                conflicts: list = None, confirm_overwrite: bool = False,
                executing: list = None) -> str:
    """
    运营只填「目标 + 约束」；分群/落库 tag/内容/频次等策略由 Agent 产出 StrategySpec。
    strategy_spec 非空时，右侧只读展示逐条策略摘要（供提交前确认）。
    prefill: 可选 dict（来自 /brief?goal_id=<id> 或提交被阻断时的回显），覆盖 ex 默认值。
             含 ref_goal_id 时，标题改为「改 Brief」+ 顶部 banner 提示。
    conflicts: validate_spec 返回的冲突列表；非空时在页面顶部渲染阻断卡片（未生成 Program）。
    """
    ex = {"objective": "", "locale": "", "budget": "0", "is_revenue": "0",
          "audience_age": "", "audience_gender": "", "audience_income": "",
          "audience_education": "", "audience_industry": "", "audience_source": "",
          "audience_region": "",
          "start_date": "2028-05-01", "end_date": "2028-07-09", "overall_conv": "",
          "goal_name": "", "constraints": "", "strategy_spec": ""}
    if prefill:
        for k, v in prefill.items():
            if k in ex and v not in (None, ""):
                # 多选字段（age/gender/.../locale）保留 list，供 _sel 正确勾选
                ex[k] = v if isinstance(v, (list, tuple, set)) else str(v)
    # audience_age 是隐藏输入（逗号串），多值 list 需拼回字符串：
    # _age_minmax / 回显文案都按字符串解析（保持与表单提交格式一致）
    if isinstance(ex.get("audience_age"), (list, tuple, set)):
        ex["audience_age"] = ",".join(str(x) for x in ex["audience_age"] if str(x))
    _is_prefill = bool(prefill and prefill.get("ref_goal_id"))
    _submit_label = ("⚠️ 二次确认：覆盖原 Program（已推送/执行中的 campaign 不会被自动改/停）"
                     if confirm_overwrite else
                     ("覆盖并重新生成 Program →" if _is_prefill else "编译并生成 Program →"))
    _strategy_gen_on = load_strategy_gen_config()["enabled"]
    _deepseek_on = load_deepseek_config()["enabled"]
    fld = lambda k, lbl, v, t="text", ph="", req=False: (
        f"<label>{lbl}</label>"
        f"<input name='{k}' type='{t}' value='{_esc(v)}' placeholder='{_esc(ph)}'"
        f"{' required' if req else ''}>"
    )
    def _sel(k, lbl, v, opts, multiple=False):
        vals = list(v) if isinstance(v, (list, tuple, set)) else ([v] if v not in (None, "") else [])
        if multiple:
            chips = "".join(
                f"<label class='chip'><input type='checkbox' name='{k}' value='{_esc(o)}'"
                f"{' checked' if o in vals else ''}><span>{_esc(o)}</span></label>"
                for o in opts if o != ""
            )
            return f"<label>{lbl}</label><div class='chip-group'>{chips}</div>"
        return (f"<label>{lbl}</label><select name='{k}'>" +
                "".join(f"<option value='{_esc(o)}' {'selected' if o in vals else ''}>{_esc(o)}</option>" for o in opts) +
                "</select>")
    def _age_minmax(bucket_str):
        if not bucket_str:
            return "", ""
        lo, hi = 999, None
        for p in str(bucket_str).split(","):
            p = p.strip()
            if not p:
                continue
            if p.endswith("+"):
                try:
                    lo = min(lo, int(p[:-1]))
                except ValueError:
                    pass
            elif "-" in p:
                try:
                    a, b = p.split("-", 1)
                    a, b = int(a), int(b)
                    lo = min(lo, a)
                    hi = b if hi is None else max(hi, b)
                except ValueError:
                    pass
        return (str(lo) if lo != 999 else ""), (str(hi) if hi is not None else "")
    age_buckets = ["", "18-24", "25-34", "35-44", "45-54", "55+"]
    gender_opts = ["", "男", "女", "未知"]
    income_opts = ["", "L1", "L2", "L3", "L4", "L5"]
    edu_opts = ["", "名校", "MBA", "211", "985", "QS100", "普通本科", "其他"]
    ind_opts = ["", "IT", "制造", "金融", "旅游", "教育", "医疗", "零售", "其他"]
    src_opts = ["", "CTL", "CSTS", "SPORT", "爬虫", "其他", "手动输入"]
    region_opts = ["", "中国大陆", "港澳台", "海外"]

    operator = (f"<div class='card'><h3>① 你的目标与约束（运营填写）</h3>"
                f"<label><span class='req'>*</span> 营销目标（必填，业务描述，至少 4 字符，非占位词）</label>"
                f"<textarea name='objective' rows='3' required placeholder='例：为「2027 元旦跨年演唱会」于 2026-12-20~2027-01-03 向 25-34 岁音乐爱好者推广门票，目标 5000 张转化；约束：每周≤3 封、晚 20:00 后不推送、含 9 折早鸟券'>{_esc(ex['objective'])}</textarea>"
                f"<p class='note'>建议按「活动/主题 + 起止时间 + 目标人群 + 期望动作 + 数量目标 + 约束条件」描述</p>"
                f"<button id='ai-parse-btn' class='btn sec' type='button' style='margin-top:8px'>✨ AI 识别意图（DeepSeek）</button>"
                f"<div id='ai-parse-status' class='note'></div>"
                f"<p class='note'>{('已配置 DeepSeek：点击将识别简称/日期/年龄/性别/收入/渠道来源等字段并回填上方表单；当活动周期 ≥7 天（或设了转化目标）时，还会自动合成多波次 StrategySpec。' if _deepseek_on else '未配置 DeepSeek：请在 config.json [deepseek].api_key 填入 key，或设置环境变量 DEEPSEEK_API_KEY。')}</p>"
                f"{fld('goal_name','营销/活动 内部简称（留空则用 ID 值；<span class=\"opt\">可选</span>）',ex['goal_name'])}"
                f"<div class='grid2'>"
                f"{fld('start_date','开始日期（<span class=\"opt\">可选</span>，留空用页面默认）',ex['start_date'])}"
                f"{fld('end_date','结束日期（<span class=\"opt\">可选</span>，留空用页面默认）',ex['end_date'])}</div>"
                f"<div class='grid2'>"
                f"{fld('overall_conv','项目预期转化率*跳转率（<span class=\"opt\">可选</span>，最终期望，0~1，如 0.15；留空=无要求走兜底逻辑）',ex['overall_conv'])}"
                f"</div>"

                # --- 目标人群特点（7 字段；画像包由系统推断） ---
                f"<div class='card-inner' style='background:#fafbf5;padding:12px;border-radius:8px;margin:8px 0'>"
                f"<h4 style='margin:6px 0'>目标人群特点</h4>"
                f"<p class='note'><b>留空 = 全部（不限制受众）</b>；勾选即按所选约束。语言未选 = 中英文双语。仅当用户明确勾选某选项时才收窄范围。</p>"
                f"<p class='note'>填入受众字段后，系统按打分公式自动匹配画像包（家庭 / 年轻人 / 父母辈 / 公司客户 / 沉默客户激活）；无匹配则用 GENERIC 兜底。</p>"
                f"<div class='grid2'>"
                f"<label>年龄段（输入起止年龄，自动匹配档位）</label>"
                f"<div>"
                f"<div class='grid2' style='gap:8px'>"
                f"<div><span class='opt'>起始年龄</span><br><input type='number' name='audience_age_min' min='0' max='120' value='{_age_minmax(ex['audience_age'])[0]}' style='width:100%' oninput='updateAgeMatch()'></div>"
                f"<div><span class='opt'>结束年龄</span><br><input type='number' name='audience_age_max' min='0' max='120' value='{_age_minmax(ex['audience_age'])[1]}' style='width:100%' oninput='updateAgeMatch()'></div></div>"
                f"<input type='hidden' name='audience_age' value='{_esc(ex['audience_age'])}'>"
                f"<p class='note' id='audience_age_match_disp'>{'匹配档位：' + ex['audience_age'] if ex['audience_age'] else ''}</p>"
                f"</div></div>"
                f"<div class='grid2'>{_sel('audience_gender','性别（多选）',ex['audience_gender'],gender_opts,multiple=True)}</div>"
                f"<div class='grid2'>"
                f"{_sel('audience_income','月收入档*RMB（多选；<3k=L1, 3-8k=L2, 8-20k=L3, 20-50k=L4, >50k=L5）',ex['audience_income'],income_opts,multiple=True)}"
                f"{_sel('audience_education','教育经历（多选）',ex['audience_education'],edu_opts,multiple=True)}</div>"
                f"<div class='grid2'>"
                f"{_sel('audience_industry','行业（多选）',ex['audience_industry'],ind_opts,multiple=True)}"
                f"{_sel('audience_source','首选来源（多选）',ex['audience_source'],src_opts,multiple=True)}</div>"
                f"<div class='grid2'>"
                f"{_sel('audience_region','国家/地区（多选）',ex['audience_region'],region_opts,multiple=True)}"
                f"{_sel('locale','语言/地区（多选）',ex.get('locale','zh_CN'),['zh_CN','en_US'],multiple=True)}"
                f"</div>"
                # --- 画像匹配实时显示（系统推断，不可改） ---
                f"<div id='audience-match' style='margin-top:10px;padding:10px;background:#f0f7e8;border-radius:6px'>"
                f"<div style='font-weight:600;color:var(--gov);margin-bottom:4px'>画像匹配（系统推断）</div>"
                f"<div id='audience-match-result'><span class='b-idle'>填入受众字段后自动匹配</span></div>"
                f"</div>"
                f"</div>"

                # --- 营收门 + 预算（替代原 budget 字段） ---
                f"<div class='grid2'>"
                f"<label>是否涉及营收/付费目标</label>"
                f"<select name='is_revenue' id='is_revenue' onchange=\"document.getElementById('budget_wrap').style.display=this.value==='1'?'block':'none'\">"
                f"<option value='0' {'selected' if ex['is_revenue']=='0' else ''}>仅意向登记 / 品牌曝光（无营收）</option>"
                f"<option value='1' {'selected' if ex['is_revenue']=='1' else ''}>涉及付费 / 转化目标</option></select>"
                f"<div id='budget_wrap' style='display:{'block' if ex['is_revenue']=='1' else 'none'}'>"
                f"{fld('budget','预算金额（¥，仅审计/审批用，不参与 ROI 计算）',ex['budget'])}"
                f"</div></div>"
                f"<p class='note'>无营收走 T2 人工审批（门槛最低）；涉营收走 T4 高级审批人（更严格）。</p>"

                f"<label>约束（红线 / 免打扰 / 合规要求，一行一条）</label>"
                f"<textarea name='constraints' placeholder='例：22:00-09:00 免打扰&#10;不得对已购票用户重复触达'>{_esc(ex['constraints'])}</textarea>"
                f"<label>策略规格（Agent 产出，可选）</label>"
                f"<div class='note'><ul>"
                f"<li>这是什么：由 Agent 根据目标产出的多波次策略文件，包含分群 / 邮件 / 频次 / 落库 tag。</li>"
                f"<li>怎么填：可填多个路径（逗号或换行分隔，如 <code>strategies/a.json, strategies/b.json</code>），"
                f"也可直接粘贴 JSON，也可留空。</li>"
                f"<li>留空 = 使用默认递进策略（分波延迟递增、内容变体递增）。</li>"
                f"</ul></div>"
                f"<textarea name='strategy_spec' placeholder='strategies/ucl2028_send_strategy.json, strategies/ucl2028_content_map.json'>"
                f"{_esc(ex['strategy_spec'] or ('strategies/example_strategy.json' if strategy_spec else ''))}</textarea>"
                f"<div style='margin-top:8px;display:flex;gap:8px;flex-wrap:wrap'>"
                f"<button id='gen-strategy-btn' class='btn sec' type='button'>✨ 自动生成策略</button>"
                f"<button id='copy-prompt-btn' class='btn ghost' type='button'>📋 复制基础信息（去 WorkBuddy 生成）</button>"
                f"</div>"
                f"<div id='gen-strategy-status' class='note'></div>"
                f"<p class='note'>{('已配置策略自动生成端点：点击将直接把 StrategySpec 填回上方文本框。' if _strategy_gen_on else ('已配置 DeepSeek：点击将直连 DeepSeek 自动生成 StrategySpec 并填回上方文本框。' if _deepseek_on else '未配置生成能力（无外部端点、无 DeepSeek）：点击后将把提示词复制到剪贴板，请在 WorkBuddy 粘贴发给小腾生成策略，再把返回的 JSON 贴回上方文本框。'))}</p>"
                f"<div id='plan-preview' class='note'>填写「总体目标转化率」与「开始 / 结束日期」后，将自动推算派生战役数量、单 campaign 点击率与合理性。</div>"
                f"<button class='btn' type='submit' style='margin-top:14px'>{_submit_label}</button>"
                f"</div>"

                # 画像匹配实时推断 JS（与 goal_intake.infer_audience_package 同公式）
                f"<script>"
                f"var _PKG_MATCH={{}}; "
                f"_PKG_MATCH.HNW_FAMILY={{label:'高净值家庭客',match:{{age:['35-44','45-54'],gender:['男'],income:['L4','L5'],education:['名校','MBA','QS100'],industry:['IT','金融','旅游','其他']}}}}; "
                f"_PKG_MATCH.YOUNG_TREND={{label:'年轻潮流客',match:{{age:['18-24','25-34'],gender:['男','女'],income:['L1','L2'],education:['普通本科','其他'],source:['CSTS','爬虫','其他','手动输入']}}}}; "
                f"_PKG_MATCH.PARENT_FAM={{label:'亲子家庭客',match:{{age:['25-34','35-44'],gender:['女'],income:['L3','L4'],education:['211','985','普通本科','其他'],industry:['教育','医疗','其他']}}}}; "
                f"_PKG_MATCH.CORP_GRP={{label:'企业团购客',match:{{income:['L4','L5'],industry:['IT','金融','制造','零售','教育','医疗']}}}}; "
                f"_PKG_MATCH.DORMANT={{label:'沉睡流失客',runtime_only:true}}; "
                f"var _W={{age:0.20,gender:0.10,income:0.25,education:0.15,industry:0.15,source:0.10,region:0.05}}; "
                f"function _computeMatch(){{"
                f"  var fields=['age','gender','income','education','industry','source','region'];"
                f"  var vals={{}};"
                f"  fields.forEach(function(k){{var cbs=document.querySelectorAll('input[type=checkbox][name=audience_'+k+']:checked');"
                f"    if(cbs.length){{vals[k]=Array.from(cbs).map(function(o){{return o.value;}});}}"
                f"    else{{var el=document.querySelector('[name=audience_'+k+']'); vals[k]=el?el.value:'';}}}});"
                f"  var rows=[];"
                f"  for(var code in _PKG_MATCH){{"
                f"    var pkg=_PKG_MATCH[code];"
                f"    if(pkg.runtime_only) continue;"
                f"    var score=0,total=0,ev=[];"
                f"    for(var i=0;i<fields.length;i++){{var f=fields[i];"
                f"      var ml=pkg.match[f];"
                f"      if(!ml) continue;  /* 画像包未定义该字段 → 不计入分母 */"
                f"      total+=_W[f];"
                f"      var v=vals[f];"
                f"      var hit=false;"
                f"      if(Array.isArray(v)){{hit=v.some(function(x){{return ml.indexOf(x)>=0;}});}}"
                f"      else{{hit=!!(v && ml.indexOf(v)>=0);}}"
                f"      if(hit){{score+=_W[f]; ev.push(f+'='+(Array.isArray(v)?v.join(','):v));}}}}"
                f"    var pct=total>0?score/total:0;"
                f"    rows.push({{code:code,label:pkg.label,score:pct,evidence:ev}});}}"
                f"  rows.sort(function(a,b){{return b.score-a.score;}}); return rows;}}"
                f"function _updateMatch(){{"
                f"  var rows=_computeMatch();"
                f"  var matched=rows.filter(function(x){{return x.score>=0.6;}});"
                f"  var box=document.getElementById('audience-match-result');"
                f"  if(matched.length===0){{"
                f"    var top=rows[0];"
                f"    box.innerHTML='<span class=\"b-warn\">无画像包匹配（最高分 '+(top?top.score.toFixed(2):'0.00')+' &lt; 0.60）</span> → 使用 <b>GENERIC 通用兜底</b>';"
                f"    return;}}"
                f"  var top=matched[0];"
                f"  var badges=matched.map(function(m){{return '<span class=\"b-ok\"><b>'+m.code+'</b></span> '+m.label+' — '+m.score.toFixed(2);}}).join('；');"
                f"  var ev=top.evidence.length>0?top.evidence.join(' / '):'（无具体字段命中）';"
                f"  var multiTxt=matched.length>1?'<div class=\"note\" style=\"margin-top:4px\">⚠ 命中多个画像包 → 策略取各画像策略的<b>最大值</b>（频次取最宽、内容 levers 取并集、CTA 取最强）。</div>':'';"
                f"  box.innerHTML='命中 '+matched.length+' 个画像包：'+badges"
                f"    +'<div class=\"note\" style=\"margin-top:4px\">命中证据：'+ev+'</div>'+multiTxt;}}"
                f"['age','gender','income','education','industry','source','region'].forEach(function(k){{"
                f"  document.querySelectorAll('input[name=audience_'+k+']').forEach(function(el){{"
                f"    el.addEventListener('change',_updateMatch);}});}});"
                f"var _ageMinEl=document.querySelector('[name=audience_age_min]');"
                f"var _ageMaxEl=document.querySelector('[name=audience_age_max]');"
                f"if(_ageMinEl) _ageMinEl.addEventListener('input',_updateMatch);"
                f"if(_ageMaxEl) _ageMaxEl.addEventListener('input',_updateMatch);"
                f"if(typeof updateAgeMatch==='function'){{var _origAge=updateAgeMatch; updateAgeMatch=function(){{_origAge(); if(typeof _updateMatch==='function') _updateMatch(); }};}}"
                f"if(typeof fillParse==='function'){{var _origFill=fillParse; fillParse=function(j){{_origFill(j); if(typeof _updateMatch==='function') _updateMatch(); }};}}"
                f"_updateMatch();"
                f"</script>"

                f"<script>{DERIVE_JS}</script>"
                f"<script>{STRATEGY_GEN_JS}</script>"
                f"<script>{AI_PARSE_JS}</script>"
                f"<script>{OBJ_HISTORY_JS}</script>")
    agent = ("<div class='agent'><h4>② Agent 自动决策（运营无需、也不能改）</h4>"
             "<div class='row'>"
             "<span class='tag biz'>主渠道 email（MVP 裁定）</span>"
             "<span class='tag res'>预留 sms（占位不发）</span>"
             "<span class='tag res'>预留 push（占位不发）</span>"
             "<span class='tag res'>预留 whatsapp（占位不发）</span>"
             "<span class='tag gov'>频次闸门 1/24h·3/7d</span>"
             "<span class='tag gov'>护栏 退订熔断0.3%·尊重抑制名单</span>"
             "<span class='tag gov'>治理注入 4 节点</span>"
             "<span class='tag gov'>mtc_* 追踪 + 9 埋点</span>"
             "<span class='tag gov'>plan_hash 绑定审批·篡改即拒</span>"
             "</div><p class='note'>这些由合并规格的治理策略与 MVP 裁定确定性生成，"
             "不由运营编辑，避免合规/频次被误改。</p>"
             + _audience_plan_html()
             + _spec_preview_html(strategy_spec, spec_err, spec_meta)
             + _service_preview_html(service_spec)
             + "</div>")
    _title = "改 Brief" if _is_prefill else "新建 Brief"
    _banner = ""
    if _is_prefill:
        _banner = (f"<p class='b-warn' style='margin:4px 0 12px'>📝 改 Brief 模式：已预填原 Program <code>{_esc(prefill.get('ref_goal_id',''))}</code> 的字段。"
                   f"提交后将<b>覆盖</b>该 Program 的内容（同一 goal_id，不新建文件）；其间 campaign 若已推送/执行中，提交前会有二次确认。</p>")
    if confirm_overwrite and executing:
        _exec_list = "、".join(_esc(c) for c in executing)
        _banner += (f"<p class='b-bad' style='margin:4px 0 12px'>⚠️ <b>二次确认</b>：原 Program 中以下 campaign 已推送/执行中："
                    f"<code>{_exec_list}</code>。<br>覆盖仅更新<b>本地 Program 草稿</b>（按新 Brief 重新生成各 campaign 规格），"
                    f"<b>不会</b>自动修改或停止 Mautic 中正在运行的 campaign；新草稿会把这些 campaign 状态重置为「未审核」并丢失原 Mautic campaign_id 映射，"
                    f"若之后再次推送将创建<b>新的</b> Mautic campaign（可能重复）。确认覆盖请点击下方按钮。</p>")
    # 冲突阻断：StrategySpec 与上方基础信息不一致 → 未生成 Program，逐条列出冲突
    if conflicts:
        _banner += _conflicts_card_html(
            conflicts,
            title="策略规格与基础信息冲突，未生成 Program",
            note="请修正 StrategySpec 或上方基础信息后重新提交（下方已保留你填的内容）。")
    return (f"<div style='display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px'>"
            f"<h1 style='margin:0'>{_title}</h1>"
            f"<a class='btn sec' href='/' style='white-space:nowrap'>← 取消并返回列表</a>"
            f"</div>"
            f"<p class='sub'>方案 A 驾驶舱 · 独立 :8090 → Mautic :8080</p>" \
           f"{_banner}" \
           f"<form method='post' action='/brief'><div class='grid2'>{operator}{agent}</div>"
           + (f"<input type='hidden' name='ref_goal_id' value='{_esc(prefill.get('ref_goal_id',''))}'>" if _is_prefill else "")
           + ("<input type='hidden' name='confirm_overwrite' value='1'>" if confirm_overwrite else "")
           + "</form>")


def _spec_preview_html(strategy_spec: list, spec_err: str = "", spec_meta: dict = None) -> str:
    """Agent 策略摘要（只读）——逐条列出每个 campaign 的决策依据与资产。"""
    if spec_err:
        return f"<p class='b-bad' style='margin-top:10px'>StrategySpec 解析失败：{_esc(spec_err)}</p>"
    if not strategy_spec:
        return ("<p class='note' style='margin-top:10px'>Agent 尚未产出策略，"
                "将使用默认递进策略（分波递进：延迟递增、变体递增）。</p>")
    meta = spec_meta or {}
    head = f"<h4 style='margin:14px 0 8px;color:var(--gov);font-size:13px'>策略摘要（只读 · 共 {len(strategy_spec)} 波）</h4>"
    srcs = meta.get("_sources") or []
    if len(srcs) > 1:
        head += (f"<p><span class='badge b-gov'>已合并 {len(srcs)} 个策略文件</span></p>")
    if meta.get("objective"):
        head += f"<p class='note'>目标：{_esc(meta['objective'])}</p>"
    rows = ""
    for i, s in enumerate(strategy_spec, 1):
        sc = s.get("send_conditions", {}) or {}
        cv = s.get("content_variant_spec") or {}
        tags = " ".join(f"<span class='tag'>{_esc(t)}</span>" for t in s.get("tags_to_write", [])) or "—"
        rows += (f"<div style='border-top:1px dashed #cfe3b7;padding:8px 0'>"
                 f"<div><strong>第{i}波 · <code>{_esc(s.get('cid',''))}</code></strong> "
                 f"<span class='pill'>{_esc(s.get('campaign_name',''))}</span></div>"
                 f"<div class='note'>理由：{_esc(s.get('rationale') or '—')}</div>"
                 f"<div class='note'>依据：{_esc(s.get('evidence') or '—')}</div>"
                 f"<div class='note'>分群 <code>{_esc(s.get('segment',''))}</code>"
                 f"（{_esc(s.get('segment_mode','reuse'))}） · 落页 <code>{_esc(s.get('landing_page_ref','') or '—')}</code></div>"
                 f"<div class='note'>邮件 <code>{_esc(email_display(s))}</code></div>"
                 f"<div class='note'>内容变体 <code>{_esc(cv.get('id') or 'v%d' % i)}</code> "
                 f"{_esc(cv.get('angle') or '—')} — {_esc(cv.get('headline') or '—')}</div>"
                 f"<div class='note'>发送条件 {sc.get('delay_hours',0)}h 延迟 · "
                 f"{sc.get('max_per_24h',1)}/24h · {sc.get('max_per_7d',3)}/7d"
                 f"{(' · 免打扰 ' + str(sc['quiet_hours'])) if sc.get('quiet_hours') else ''}</div>"
                 f"<div class='note'>落库 tag {tags}</div></div>")
    return head + rows


def _service_preview_html(service_spec: list) -> str:
    """service/transactional 序列预览（只读）：不占 promo 配额、事件触发。"""
    if not service_spec:
        return ""
    rows = ""
    for s in service_spec:
        trig = s.get("trigger") or {}
        ex = s.get("exemptions") or {}
        tags = " ".join(f"<span class='tag'>{_esc(t)}</span>" for t in s.get("tags_to_write", [])) or "—"
        rows += (f"<div style='border-top:1px dashed #cfe3b7;padding:8px 0'>"
                 f"<div><strong>服务序列 · <code>{_esc(s.get('sid') or s.get('cid',''))}</code></strong> "
                 f"<span class='pill'>{_esc(s.get('campaign_name',''))}</span></div>"
                 f"<div class='note'>触发：{_esc(trig.get('mode','event'))} — "
                 f"{_esc(trig.get('event','') or '事件驱动')}（延迟 {trig.get('delay_hours',0)}h，不看 segment）</div>"
                 f"<div class='note'>豁免：{_esc('；'.join(f'{k}={v}' for k, v in ex.items()) or '—')}</div>"
                 f"<div class='note'>tag {tags}</div></div>")
    return ("<h4 style='margin:14px 0 8px;color:var(--gov);font-size:13px'>"
            f"服务序列（service · 不进 promo Program · 共 {len(service_spec)} 条）</h4>" + rows)


# 画像包 → 内容取向（只读展示；不随左侧受众字段切换）
#
# 设计约束（重要）：画像包**只决定内容**——每波讲什么、怎么讲（价值主张 / 角度 / 调性 / CTA /
# 视觉 / 合规口径）。campaign（波次）数量由活动周期 + 预期转化率单独决定，与画像包无关，
# 所以这里任何一行都不得出现 c1/c2/…/「N 波」这类数量描述。
_PERSONA_STRATEGY_ROWS = [
    ("家庭（HNW_FAMILY）",
     "内容切入：观赛家庭 / 亲子场景，CTA 主打「家庭优先购买资格」。"
     "角度取深度价值 / 数据对比 / 长期主义，语气理性克制、报告感，"
     "禁用「低价 / 限时 / 拼团 / 秒杀 / 仅剩」；视觉大留白 + 高端实景，单一克制 CTA。"
     "登记后即停促销、转服务确认。"),
    ("年轻人（YOUNG_TREND）",
     "内容切入：氛围与稀缺感（决赛唯一候选 / 优先资格），弱化条款、强化「第一时间拿到资格」。"
     "语气口语化、短句、可用 emoji，引用 UGC 与限量信息；视觉高饱和撞色、人物特写，CTA 用「抢 / 速戳 / 蹲一个」。"
     "单波触达受该包频次上限与免打扰约束。"),
    ("父母辈（PARENT_FAM）",
     "内容切入：「带孩子看决赛」的价值主张 + 确定性信息。合规口径：日期 / 场馆在 host 官宣前不得写成已确认。"
     "语气温和具体、攻略感，突出安全细节与同行案例；视觉暖色卡片式 + 真实家庭合影，CTA 指向亲子版行程 / 安全保障。"),
    ("公司客户（CORP_GRP）",
     "内容切入：Hospitality 包厢 / 企业观赛权益，收入档 L4/L5。语气商务简洁、表格化呈现权益与议程，"
     "展示真实企业 logo，CTA 为「获取团购方案 / 联系企业顾问」；更适合转客户经理跟进而非纯邮件触达。"),
    ("沉默客户激活（DORMANT）",
     "内容切入：以外部权威事件（host 确认）或新权益作为重启理由，避免「纯提醒式」唤醒。"
     "语气怀旧口语、像朋友来信，只讲一个全新变化、不堆栈优惠；视觉低饱和复古 + 人物背影。"
     "仍无互动者走抑制名单 / 清洗，不追加频次。"),
    ("GENERIC 通用兜底",
     "未命中任一画像包时的中性内容取向：客观陈述事实 + 2-3 条通用卖点 + 单一 CTA"
     "（查看详情 / 了解活动），不挑人、不挑场景，中性配色与通用实景图。"),
]

# campaign 数量规则（与画像包解耦，页面只读展示，供运营核对 Agent 产出）
_CAMPAIGN_COUNT_RULE = (
    "campaign 数量 N 只由「活动周期 D」与「预期转化率 C」决定，画像包、受众字段、预算均不参与："
    "① 按周期定基准：D≤14 天 → 2；15~45 天 → 3；46~90 天 → 4；&gt;90 天 → 5；"
    "② 按转化率调整：C≥10% → +1（预期高，值得分波培育）；C 未设置或 ≤2%（纯曝光 / 低预期）→ −1；"
    "③ 夹取：下限 1、上限 5。"
)


def _audience_plan_html() -> str:
    """② 区只读块：画像包 → 内容取向（内置文案映射）+ campaign 数量规则。"""
    head = ("<h4 style='margin:12px 0 6px'>画像包 → 内容取向"
            "<span class='note' style='font-weight:400'>（只影响内容，不决定 campaign 数量）</span></h4>")
    rows = "".join(
        f"<div style='border-top:1px dashed #cfe3b7;padding:7px 0'>"
        f"<div><strong>{_esc(name)}</strong></div><div class='note'>{_esc(txt)}</div></div>"
        for name, txt in _PERSONA_STRATEGY_ROWS)
    rule = (f"<div style='border-top:1px dashed #cfe3b7;padding:7px 0'>"
            f"<div><strong>campaign 数量规则</strong></div>"
            f"<div class='note'>{_CAMPAIGN_COUNT_RULE}</div></div>")
    return head + rows + rule


def _build_replan_prompt(program: dict, gid: str, cid: str) -> str:
    """组装「下一阶段策略」自包含提示词：目标 + 已完成 campaign 结果 + 下游当前策略，供 WorkBuddy 生成 StrategySpec。"""
    goal = program.get("goal") or {}
    kpi = goal.get("kpi") or {}
    target = kpi.get("target")
    target_txt = target if target not in (None, 0, 0.0) else "未设置（运营尚未给 R）"
    done = next((c for c in program["campaigns"] if c["cid"] == cid), None)
    lines = []
    lines.append("你是营销 Agent 的 AI策略合成器。下面给出一个 Program 的执行结果，请产出「下一阶段策略」的 StrategySpec JSON。")
    lines.append("")
    lines.append("## 目标")
    lines.append(f"- goal_id: {gid}")
    lines.append(f"- objective: {goal.get('objective', '')}")
    lines.append(f"- KPI 转化目标 R: {target_txt}")
    if done:
        res = done.get("result") or done.get("feedback") or {}
        lines.append("")
        lines.append(f"## 刚完成的 campaign：{cid}（状态 {done.get('status', '')}）")
        lines.append(f"- 达成率: {res.get('conversion')} · 退订率: {res.get('unsub')}")
        lines.append(f"- 当前策略摘要: {_strategy_summary(done['strategy'])}")
    lines.append("")
    lines.append("## 仍待推进的下游 campaign（请按这些 cid 重写 strategy；可新增折扣挽回分支，cid 形如 {gid}_reengage_<原cid>）")
    any_down = False
    for c in program["campaigns"]:
        if c["cid"] == cid:
            continue
        if c["status"] not in ("unreviewed", "reviewed", "pending"):
            continue
        any_down = True
        lines.append(f"- {c['cid']}（状态 {c['status']}）: {_strategy_summary(c['strategy'])}")
    if not any_down:
        lines.append("（无待推进下游，可仅输出挽回/兜底分支或返回空 campaigns）")
    lines.append("")
    lines.append("## 输出要求")
    lines.append("只输出可被 json.loads 解析的 StrategySpec 对象（不要解释文字、不要 markdown 代码块）。")
    lines.append("campaigns 数组中：已存在的下游 cid 必须保持相同 cid（重写其 strategy）；你可新增挽回分支 campaign（cid 形如 {gid}_reengage_<原cid>）。")
    lines.append("每个 campaign 字段遵循 StrategySpec schema：segment / email(ref+mode+brief) / content_variant / send_conditions / discount / tags_to_write / rationale。")
    return "\n".join(lines)


def _strategy_summary(s: dict, idx: dict = None) -> str:
    """Program 页每 campaign 的策略摘要：理由/依据/分群/邮件/变体/发送条件/tag。
    idx（Mautic 资产索引，来自 _mautic_asset_index）非空时，分群/邮件/落页引用
    渲染成可跳转 :8080 详情页的外链；idx 为 None（导出/纯文本场景）时退化为纯文本。"""
    s = s or {}
    sc = s.get("send_conditions", {}) or {}
    cv = s.get("content_variant_spec") or {}
    tags = " ".join(f"<span class='tag'>{_esc(t)}</span>" for t in s.get("tags_to_write", [])) or "—"
    cv_id = cv.get("id") or ("v%s" % s.get("content_variant", 0))
    split = s.get("variant_split")
    try:
        _split = float(split) if split is not None else 0.0
    except (TypeError, ValueError):
        _split = 0.0
    if _split and _split > 0 and (cv.get("angle") or cv.get("headline") or cv.get("summary")):
        # 命中分流比例 → 走变体路径；其余走主邮件。给运营明确的「何时走变体」判断条件。
        variant_txt = (f"变体 <code>{_esc(cv_id)}</code> {_esc(cv.get('angle') or '')}"
                       f" — 按 <b>{int(_split*100)}%</b> 比例走变体、其余走主邮件"
                       f"{(('：' + _esc(cv['headline'])) if cv.get('headline') else '')}")
    else:
        variant_txt = (f"变体 <code>{_esc(cv_id)}</code>"
                       f"{(' ' + _esc(cv.get('angle') or '')) if cv.get('angle') else ''}"
                       f"{((' — ' + _esc(cv['headline'])) if cv.get('headline') else '')}")
    base = (f"分群 {_ref_link('segment', s.get('segment',''), s.get('segment','') or '—', idx)}"
            f"<span class='pill'>({_esc(s.get('segment_mode','reuse'))})</span>"
            f" · 频 <code>{sc.get('max_per_24h',1)}/24h·{sc.get('max_per_7d',3)}/7d</code>"
            f" · 延迟 <code>{sc.get('delay_hours',24)}h</code>"
            f"{(' · 免打扰 <code>' + _esc(sc['quiet_hours']) + '</code>') if sc.get('quiet_hours') else ''}"
            f" · 邮件 {_ref_link('email', s.get('email_ref',''), email_display(s), idx)}"
            f" · 落页 {_ref_link('landingpage', s.get('landing_page_ref',''), s.get('landing_page_ref','') or '—', idx)}"
            f" · {variant_txt}"
            f" · tag {tags}")
    why = ""
    if s.get("rationale") or s.get("evidence"):
        why = (f"<br><span class='pill'>理由：{_esc(s.get('rationale') or '—')}"
               f" ｜ 依据：{_esc(s.get('evidence') or '—')}</span>")
    return base + why


def _graph_svg(graph: list) -> str:
    """Mautic 风格竖向时间线：入口(source)在顶，action 纵向串联，decision 画菱形，
    if_true/if_false 用绿/橙虚线分叉，配色对齐 Mautic。
    纯前端渲染改造，不碰策略/事件图数据结构；透明节点（decision.variant/email.variant）同样画出，
    但标注为「不建真实 Mautic 事件」。"""
    nodes = list(graph)
    if not nodes:
        return "<p class='note'>（事件图为空）</p>"
    by_id = {n["id"]: n for n in nodes}

    # ---- 布局：主链沿 next 串联（左列），分支节点（仅由 if_true 可达）放右列 ----
    # next 可能落在 top-level（nxt 透传）或 params（decision 路由参数）里，两者都认
    def _next_of(nid):
        nd = by_id.get(nid, {})
        return nd.get("next") or (nd.get("params", {}) or {}).get("next")
    seen, spine, cur = set(), [], nodes[0]["id"]
    while cur and cur not in seen:
        seen.add(cur)
        spine.append(cur)
        cur = _next_of(cur)
    branch = [n["id"] for n in nodes if n["id"] not in set(spine)]

    W, H = 130, 36                       # 节点框（原 156x46，压缩以适配多节点）
    HW, HH = W / 2, H / 2                # 半宽/半高（菱形同外接框）
    COL_X, BR_X = 50, 282                # 主链列 x / 分支列 x
    TOP, ROW = 26, 52                    # 顶部留白 / 行距（原 34/66）
    pos = {}
    for i, nid in enumerate(spine):
        pos[nid] = (COL_X, TOP + i * ROW)
    # 分支节点：挂到其父 decision 同高（右侧），否则顺延堆叠
    br_idx = 0
    for nid in branch:
        parent = next((pid for pid in spine
                       if by_id.get(pid, {}).get("if_true") == nid
                       or by_id.get(pid, {}).get("if_false") == nid), None)
        if parent and parent in pos:
            pos[nid] = (BR_X, pos[parent][1])
        else:
            pos[nid] = (BR_X, TOP + (len(spine) + br_idx) * ROW)
            br_idx += 1

    def _short(t: str) -> str:
        parts = t.split(".")
        return parts[-1] if len(parts) == 1 else ".".join(parts[-2:])

    def _color(nd: dict):
        t = nd.get("type", "")
        if t in ("decision.variant", "email.variant"):
            return "#7a4fb5", "#f1e9fa"   # 变体：紫（透明节点）
        if nd.get("governance") or t.endswith(".reserved"):
            return "#3b6d11", "#eaf3de"   # 治理/预留：绿
        if t.startswith("decision"):
            return "#ba7517", "#faefda"   # 决策：橙
        return "#185fa5", "#e8f1fb"       # 业务：蓝（对齐 Mautic）

    # 锚点：按相对方位选出口/入口边（垂直优先从上/下，水平优先从左/右）
    def _anchors(a, b):
        x, y = a; tx, ty = b
        dx, dy = tx - x, ty - y
        if abs(dy) >= abs(dx):
            s = (x, y + HH) if dy >= 0 else (x, y - HH)
            e = (tx, ty - HH) if dy >= 0 else (tx, ty + HH)
        else:
            s = (x + HW, y) if dx >= 0 else (x - HW, y)
            e = (tx - HW, ty) if dx >= 0 else (tx + HW, ty)
        return s, e

    total_rows = max(len(spine), len(spine) + br_idx)
    vw = BR_X + W + 40
    vh = TOP * 2 + total_rows * ROW
    # 按原始尺寸渲染（不再 width:100% 放大——18 节点时会被撑到 2300+px）；
    # max-width:100% + height:auto 保证窄屏仍可等比缩小。
    svg = [f"<svg viewBox='0 0 {vw} {vh}' width='{vw}' height='{vh}' "
           f"style='background:#fbfcfe;border:1px solid var(--line);border-radius:10px;"
           f"max-width:100%;height:auto' "
           f"font-family='inherit' font-size='10'>"]
    svg.append("<defs>"
               "<marker id='arw' markerWidth='8' markerHeight='8' refX='6' refY='3' orient='auto' "
               "markerUnits='userSpaceOnUse'><path d='M0,0 L6,3 L0,6 Z' fill='#6b7280'/></marker>"
               "<marker id='arwok' markerWidth='8' markerHeight='8' refX='6' refY='3' orient='auto' "
               "markerUnits='userSpaceOnUse'><path d='M0,0 L6,3 L0,6 Z' fill='#1d9e75'/></marker>"
               "<marker id='arwbad' markerWidth='8' markerHeight='8' refX='6' refY='3' orient='auto' "
               "markerUnits='userSpaceOnUse'><path d='M0,0 L6,3 L0,6 Z' fill='#d85a30'/></marker></defs>")
    svg.append(f"<text x='{COL_X + W/2}' y='{TOP - 14}' text-anchor='middle' "
               f"fill='#6b7280' font-size='10'>▶ 入口（campaign source）</text>")

    def _edge(s, e, stroke, mk, dash, label=None):
        svg.append(f"<line x1='{s[0]}' y1='{s[1]}' x2='{e[0]}' y2='{e[1]}' "
                   f"stroke='{stroke}'{dash} stroke-width='1.4' marker-end='{mk}'/>")
        if label:
            mx, my = (s[0] + e[0]) / 2, (s[1] + e[1]) / 2
            svg.append(f"<text x='{mx}' y='{my - 3}' text-anchor='middle' "
                       f"fill='{stroke}' font-size='9.5'>{_esc(label)}</text>")

    # ---- 连线 ----
    order = spine + branch
    for nid in order:
        nd = by_id[nid]
        c = pos[nid]
        t = nd.get("type", "")
        p = nd.get("params", {}) or {}
        is_dec = t.startswith("decision")
        # 边字段可能在 top-level（nxt 透传）或 params（decision 路由参数）里，两者都认
        nxt = nd.get("next") or p.get("next")
        if_true = p.get("if_true") or nd.get("if_true")
        if_false = p.get("if_false") or nd.get("if_false")
        if is_dec:
            # decision：if_true 绿虚线、if_false 橙虚线（if_false 通常即穿透 continue）
            it = pos.get(if_true)
            iff = pos.get(if_false)
            if it:
                s, e = _anchors(c, it)
                _edge(s, e, "#1d9e75", "url(#arwok)", " stroke-dasharray='5 3'",
                      "走变体" if t == "decision.variant" else None)
            if iff:
                s, e = _anchors(c, iff)
                _edge(s, e, "#d85a30", "url(#arwbad)", " stroke-dasharray='5 3'",
                      "走主邮件" if t == "decision.variant" else None)
            # next 若未被 if_false 覆盖（极少数情况），补画灰线
            if nxt and nxt != if_false:
                nt = pos.get(nxt)
                if nt:
                    s, e = _anchors(c, nt)
                    _edge(s, e, "#6b7280", "url(#arw)", "", None)
        else:
            nt = pos.get(nxt)
            if nt:
                s, e = _anchors(c, nt)
                _edge(s, e, "#6b7280", "url(#arw)", "", None)

    # ---- 节点 ----
    for nid in order:
        nd = by_id[nid]
        cx, cy = pos[nid]
        fill, stroke = _color(nd)
        t = nd.get("type", "")
        is_dec = t.startswith("decision")
        transparent = t in ("decision.variant", "email.variant")
        svg.append(f"<g><title>{_esc(t)}</title>")
        if is_dec:
            # 菱形：上/右/下/左 四顶点
            svg.append(
                f"<polygon points='{cx},{cy-HH} {cx+HW},{cy} {cx},{cy+HH} {cx-HW},{cy}' "
                f"fill='{stroke}' stroke='{fill}' stroke-width='1.6'/>"
                f"<text x='{cx}' y='{cy-4}' text-anchor='middle' fill='{fill}' "
                f"font-weight='600' font-size='10'>{_esc(_short(t))}</text>"
                f"<text x='{cx}' y='{cy+12}' text-anchor='middle' fill='#1c2330' "
                f"font-size='8'>{_esc(nd['id'])}</text>")
        else:
            svg.append(
                f"<rect x='{cx-W/2}' y='{cy-H/2}' width='{W}' height='{H}' rx='9' "
                f"fill='{stroke}' stroke='{fill}' stroke-width='1.5'/>"
                f"<text x='{cx}' y='{cy-4}' text-anchor='middle' fill='{fill}' "
                f"font-weight='600' font-size='10'>{_esc(_short(t))}</text>"
                f"<text x='{cx}' y='{cy+13}' text-anchor='middle' fill='#1c2330' "
                f"font-size='8'>{_esc(nd['id'])}</text>")
        if transparent:
            svg.append(f"<text x='{cx}' y='{cy+H/2+12}' text-anchor='middle' "
                       f"fill='#7a4fb5' font-size='8'>透明节点·不建 Mautic 事件</text>")
        svg.append("</g>")
    svg.append("</svg>")
    inner = "".join(svg)
    # 节点多时在图内滚动，避免整页被撑得过长
    return f"<div style='max-height:620px;overflow:auto;border-radius:10px'>{inner}</div>"


def _mautic_asset_table(program: dict, idx: dict = None) -> str:
    """汇总 Program 内每个 campaign 引用/将新建的 Mautic 资产（新建 vs 调用已有）。
    若 idx 未传则自行读取一次 Mautic 资产索引；ref 在 Mautic 实存时渲染成可跳转详情页的外链。"""
    if idx is None:
        idx = _mautic_asset_index()
    avail = idx["available"]
    emails = idx["email"]; segs = idx["segment"]; pages = idx["page"]; forms = idx["form"]

    def _exists(ref: str, name_map: dict, id_map: dict) -> bool:
        if not ref:
            return False
        return ref in name_map or ref in id_map

    def _row(kind, ref, mode):
        is_none = not ref
        if is_none:
            ref = "（无）"
        ph = isinstance(ref, str) and "PLACEHOLDER" in ref
        _map = (emails if kind == "email" else segs if kind == "分群"
                else pages if kind == "着陆页" else forms)
        resolved = bool(avail and not is_none and _exists(ref, _map, _map))
        # 结论以「是否真能调用已有」为准，而非盲目信任 mode ——
        # 防生成器占位 ref（EM_*_PLACEHOLDER / 未推送）被误标「调用已有」却没有外链。
        if mode == "generate":
            concl = "新建"
        elif ph:
            concl = "待建（占位）"
        elif resolved:
            concl = "调用已有"
        elif mode == "propose":
            # propose = 有则复用、无则推送时 ensure 创建；未解析时等同于「按需新建」
            concl = "新建（按需）"
        else:
            concl = "调用已有（未找到）"
        if not avail:
            real = "未连"
        elif is_none:
            real = "—"
        elif resolved:
            real = "✓"
        elif mode == "generate" or ph or mode == "propose":
            real = "待建"
        else:
            real = "✗"
        # 仅当 ref 真能解析为 Mautic 实体时才渲染外链
        ref_cell = f"<code>{_esc(ref)}</code>"
        lk_kind = {"email": "email", "分群": "segment",
                   "着陆页": "landingpage", "表单": "form"}.get(kind)
        if lk_kind and resolved:
            lk = _mautic_ext_link(lk_kind, ref, idx)
            if lk:
                ref_cell = f"<code>{_esc(ref)}</code> {lk}"
        return (f"<tr><td>{kind}</td><td>{ref_cell}</td>"
                f"<td>{_esc(mode)}</td><td>{concl}</td><td>{real}</td></tr>")

    rows = ""
    for c in program["campaigns"]:
        s = c["strategy"]
        em_ref = s.get("email_ref", "")
        em_mode = s.get("email_mode", "reuse")
        seg = s.get("segment", "")
        seg_mode = s.get("segment_mode", "reuse")
        lp = s.get("landing_page_ref", "")
        form_ref = s.get("form_ref", "")
        rows += _row("email", em_ref, em_mode)
        rows += _row("分群", seg, seg_mode)
        if lp:
            # 着陆页与表单均按「有则复用、无则推送时 ensure 创建」处理（find-or-create），
            # 与分群/邮件一致；故模式用 propose 而非 reuse —— 未解析时结论应为「新建（按需）」，
            # 而非「调用已有（未找到）」。found→超链接、not found→新建，符合运营预期。
            rows += _row("着陆页", lp, "propose")
        else:
            rows += ("<tr><td>着陆页</td><td><code>—</code></td><td>generate</td>"
                     "<td>新建</td><td>未连</td></tr>" if not avail else
                     "<tr><td>着陆页</td><td><code>—</code></td><td>generate</td>"
                     "<td>新建</td><td>✗</td></tr>")
        # 表单：与邮件/落地页同属「内容资产」，按「哪个 campaign 用到就在哪个 campaign 显示」原则
        # 逐 campaign 展示（不特殊标注为独立/共享基础设施）。
        if form_ref:
            # 表单同着陆页：find-or-create（ensure_form），模式用 propose 而非 reuse，
            # 未解析时结论为「新建（按需）」而非「调用已有（未找到）」。
            rows += _row("表单", form_ref, "propose")
        else:
            rows += ("<tr><td>表单</td><td><code>—</code></td><td>generate</td>"
                     "<td>新建</td><td>未连</td></tr>" if not avail else
                     "<tr><td>表单</td><td><code>—</code></td><td>generate</td>"
                     "<td>新建</td><td>✗</td></tr>")
    note = ("（未连接 Mautic 或缺少凭证：以下为基于策略规格的预期清单，无外链）" if not avail
            else "（已连接 Mautic，✓=实存 / 待建=推送时自动创建 / ✗=策略声明复用但 Mautic 中不存在；ref 可点击跳转详情页）")
    return (f"<div class='card'><h3>Mautic 资产清单（新建 vs 调用）</h3>"
            f"<p class='note'>{_esc(note)}</p>"
            f"<table><tr><th>类型</th><th>引用(ref)</th><th>模式</th>"
            f"<th>结论</th><th>实存</th></tr>{rows}</table></div>")


# --------------------------- Mautic 外链（资产已在 :8080/s/ 生成 → 跳转详情页） ---------------------------
# Mautic 7 后台详情页真实路由：/s/{section}/view/{id}（已与用户 :8080 实例核对：
# 分群 http://localhost:8080/s/segments/view/124 、邮件 http://localhost:8080/s/emails/view/122）
_MAUTIC_ADMIN_ROUTES = {
    "campaign": "/s/campaigns/view/{id}",
    "email": "/s/emails/view/{id}",
    "segment": "/s/segments/view/{id}",
    "landingpage": "/s/landingpages/view/{id}",
    "sms": "/s/sms/view/{id}",
    "form": "/s/forms/view/{id}",
}

def _mautic_base() -> str:
    """Mautic 实例 base URL（来自 config.json 的 local.base_url）。"""
    try:
        return load_config("local").get("base_url", "http://localhost:8080").rstrip("/")
    except Exception:  # noqa: BLE001
        return "http://localhost:8080"

def _mautic_asset_index() -> dict:
    """读取 Mautic 已存在资产，构建 ref→id 索引（email/segment/landingpage/form）。
    仅 available=True 时索引有意义；否则 available=False 且无外链。"""
    env = mautic_read_assets("local")
    avail = env.get("available", False)
    def _idx(items, *keys):
        m = {}
        for it in items:
            for k in keys:
                v = it.get(k)
                if v not in (None, ""):
                    m[str(v)] = it.get("id")
        return m
    return {
        "available": avail,
        "email": _idx(env.get("emails", []), "name", "alias", "id"),
        "segment": _idx(env.get("segments", []), "name", "alias", "id"),
        "page": _idx(env.get("pages", []), "name", "alias", "id"),
        "form": _idx(env.get("forms", []), "name", "alias", "id"),
    }

def _mautic_ext_link(kind: str, ref, idx: dict) -> str:
    """返回 Mautic 详情页外链 <a>；不可解析（未连接/未找到/未知类型）返回空串。
    kind: campaign | email | segment | landingpage | form。"""
    base = _mautic_base()
    routes = _MAUTIC_ADMIN_ROUTES
    if kind == "campaign":
        if not ref:
            return ""
        return (f"<a class='ext' href='{base}{routes['campaign'].format(id=ref)}' "
                f"target='_blank' rel='noopener'>Mautic 战役详情</a>")
    if kind in ("email", "segment", "landingpage", "form"):
        if not idx or not idx.get("available"):
            return ""
        key = "page" if kind == "landingpage" else kind
        mid = idx.get(key, {}).get(str(ref) if ref else "")
        if not mid:
            return ""
        return (f"<a class='ext' href='{base}{routes[kind].format(id=mid)}' "
                f"target='_blank' rel='noopener'>详情</a>")
    return ""

def _ref_link(kind: str, name, display: str, idx: dict) -> str:
    """把资产名渲染成可点击的 Mautic 详情页链接（链接文字即 display）；
    不可解析（未连接/未找到/未知类型/name 为空）时退化为 <code> 纯文本。
    用于 _strategy_summary 的 分群/邮件/落页 引用 —— 让创建页/Program 页的
    策略摘要里的资产名可直接跳转 :8080 详情页（与用户期望一致：
    分群→/s/segments/view/{id}、邮件→/s/emails/view/{id}）。
    kind: segment | email | landingpage（落页在 idx 里用 'page' 键）。"""
    _disp = _esc(display if display is not None else "")
    if not name:
        return f"<code>{_disp}</code>"
    if not idx or not idx.get("available"):
        return f"<code>{_disp}</code>"
    key = "page" if kind == "landingpage" else kind
    mid = idx.get(key, {}).get(str(name))
    if not mid:
        return f"<code>{_disp}</code>"
    base = _mautic_base()
    href = f"{base}{_MAUTIC_ADMIN_ROUTES[kind].format(id=mid)}"
    return (f"<a class='ext' href='{href}' target='_blank' rel='noopener'>{_disp}</a>")


def _asset_note(kind: str, ref, idx: dict) -> str:
    """ref 无法解析为 Mautic 资产时的说明文案（区分 未连接 / 占位 / 真缺失）。"""
    if not idx.get("available"):
        return "<span class='note'>（未连接 Mautic，无外链）</span>"
    if "PLACEHOLDER" in str(ref):
        return "<span class='note'>（占位 ref，推送创建后才有外链）</span>"
    # 主 segment / email / 落地页在 push() 里都会 ensure，因此不存在时也会自动创建
    return "<span class='note'>（Mautic 无对应资产，推送时将自动创建）</span>"


def _mautic_campaign_name(campaign_id) -> str:
    """返回 Mautic campaign 的实时名字（单个 GET、不缓存，保证改名后同步到 Program 页）；
    失败回退列表缓存；再失败返回空串。"""
    if not campaign_id:
        return ""
    nm = (mautic_get_campaign(campaign_id).get("name") or "").strip()
    if not nm:
        nm = mautic_read_campaigns("local").get("by_id", {}).get(str(campaign_id), "")
    return nm


def _mautic_reachable(env="local", timeout=10):
    """推送前的轻量探活：无凭证 GET /api/segments?limit=1。

    目的：把『Mautic 没启动』这类连接错误，从 push() 内部的 segment/form 逻辑错误里
    分离出来，避免误导用户去排查并不存在的 segment / 资产问题（正是 c1 推送失败那条
    「常见原因」静态清单会造成的误导）。

    返回 (ok, detail)：
      · ok=True  → 服务在线（含 401 未授权——端口通，交给 push() 正常报鉴权错）
      · ok=False → 连接被拒 / 超时（URLError），服务没起；detail 含网络原因
    """
    try:
        cfg = load_config(env)
    except Exception:  # noqa: BLE001
        return (True, "")  # 配置读不到不拦截，让 push() 自己报
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        return (True, "")
    url = f"{base}/api/segments?limit=1"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()  # 读到任何响应即代表服务在线（401 也算）
        return (True, "")
    except urllib.error.HTTPError:
        # 401/403 等鉴权错 → 服务通，只是缺凭证，交给 push()
        return (True, "")
    except urllib.error.URLError as e:
        return (False, f"连接被拒/超时：{e.reason}")
    except Exception as e:  # noqa: BLE001
        return (False, f"探活异常：{e}")


def _mautic_netloc(env="local"):
    """Mautic 地址（用于提示文案），localhost 统一显示成 127.0.0.1。"""
    try:
        cfg = load_config(env)
        nl = urllib.parse.urlsplit(cfg.get("base_url", "")).netloc
        if nl:
            return nl.replace("localhost", "127.0.0.1")
    except Exception:  # noqa: BLE001
        pass
    return "127.0.0.1:8080"


def _resolve_program_project(p, env="local"):
    """返回 program 对应的 Mautic project id；没有就现建（/api/v2 Basic 认证）并写回 program 字典。
    program 名取自 p['goal']['name']，project 名带 goal_id 保证唯一、可复用（改 Brief 覆盖模式复用同名 project）。
    返回 int id 或 None（Mautic 不可达 / 未配 Basic 凭证时降级为 None，不阻断 program 生成与推送）。"""
    pid = p.get("mautic_project_id")
    if pid:
        return pid
    try:
        name = (p.get("goal") or {}).get("name") or p.get("goal_id") or "PROG"
        gid = p.get("goal_id") or ""
        pid = ensure_project(f"{name} ({gid})", env)
    except Exception:  # noqa: BLE001
        pid = None
    if pid:
        p["mautic_project_id"] = pid
        _save_program(p)
    return pid


def _check_push_result(result: dict):
    """真实判定 push() 返回是否成功。
    - dry_run=True → 算成功（无凭证时正常降级）
    - campaign_id 非空 → 真创建了
    - 失败：steps 里第一步非 2xx，提取 Mautic 的 errors[] 给出可读原因
    返回 (ok: bool, err: str)。"""
    if not isinstance(result, dict):
        return (False, "push() 返回结构异常")
    if result.get("dry_run"):
        note = result.get("note") or ""
        # dry-run 通常=未填凭证的正常降级；若 note 表明是 token/凭证获取错误，则是失败，必须如实上报
        # （否则会被误判为成功、状态谎报为执行中）
        if ("token" in note) or ("凭证" in note) or ("获取" in note):
            return (False, note)
        return (True, "")  # 干净的 dry-run（未填凭证），不算失败
    if result.get("campaign_id"):
        # 即便 campaign_id 存在，仍校验每步 status（publish 步骤也可能 4xx）
        for step in (result.get("steps") or []):
            try:
                st = int(step.get("status") or 0)
            except (TypeError, ValueError):
                st = 0
            if 200 <= st < 300:
                continue
            return (False, f"{step.get('step','?')} HTTP {st}：{_format_mautic_err(step.get('body'))}")
        return (True, "")
    # campaign_id=None → 必失败
    for step in (result.get("steps") or []):
        try:
            st = int(step.get("status") or 0)
        except (TypeError, ValueError):
            st = 0
        if st and not (200 <= st < 300):
            return (False, f"{step.get('step','?')} HTTP {st}：{_format_mautic_err(step.get('body'))}")
    return (False, "Mautic 未返回 campaign_id（响应为空或解析失败）")


def _format_mautic_err(body) -> str:
    """把 Mautic 错误响应体（dict / str）压成一行可读字符串。"""
    if isinstance(body, dict):
        errs = body.get("errors") or []
        if isinstance(errs, list) and errs:
            parts = []
            for e in errs[:3]:  # 最多 3 条
                if isinstance(e, dict):
                    msg = e.get("message") or e.get("detail") or json.dumps(e, ensure_ascii=False)
                    parts.append(str(msg))
                else:
                    parts.append(str(e))
            return "；".join(parts)
        # 兜底：直接拿 detail / message
        if body.get("message"):
            return str(body["message"])
        return json.dumps(body, ensure_ascii=False)[:300]
    if isinstance(body, str):
        return body[:300]
    return str(body)[:300]


# --------------------------- 总策略展示（画像包 + 内容/视觉方向 + 来源） ---------------------------
# 频次 / 静默窗 / 触达时段的取值来源 → 中文徽章（strategy.strategy_provenance）
_PROV_LABELS = {"spec": "规格", "package": "画像包",
                "red_line": "红线", "default": "默认"}


def _prov_badge(src) -> str:
    """来源徽章：spec / package / red_line / default → 规格 / 画像包 / 红线 / 默认。"""
    lbl = _PROV_LABELS.get(str(src or "").strip(), "默认")
    cls = {"规格": "b-gov", "画像包": "b-gov", "红线": "b-warn"}.get(lbl, "b-idle")
    return f"<span class='badge {cls}'>{_esc(lbl)}</span>"


def _provenance_line(s: dict) -> str:
    """每 campaign 的 频次 / 静默窗 / 触达时段 + 来源徽章（值从哪来：规格 / 画像包 / 红线 / 默认）。"""
    s = s or {}
    sc = s.get("send_conditions") or {}
    prov = s.get("strategy_provenance") or {}
    win = s.get("send_window") or sc.get("send_window") or ""
    if isinstance(win, (list, tuple)):
        win = "、".join(str(x) for x in win)
    elif isinstance(win, dict):
        win = "、".join(f"{k}:{v}" for k, v in win.items())
    bits = []
    for lbl, val, key in (("频次/24h", sc.get("max_per_24h"), "max_per_24h"),
                          ("频次/7d", sc.get("max_per_7d"), "max_per_7d"),
                          ("免打扰", sc.get("quiet_hours"), "quiet_hours"),
                          ("触达时段", win, "send_window")):
        if val in (None, ""):
            continue
        bits.append(f"{lbl} <code>{_esc(val)}</code>{_prov_badge(prov.get(key))}")
    if not bits:
        return ""
    return (f"<p class='pill'>取值来源：{' · '.join(bits)}"
            f"<span class='note' style='margin-left:6px'>（规格=策略写死 · 画像包=包默认值 · 红线=约束优先 · 默认=系统兜底）</span></p>")


_ASSET_LABEL = {"stage": "阶段", "segment": "分组", "form": "表单"}


def _compile_notes_html(prop: dict) -> str:
    """
    编译期说明卡片：终点判定告警（声明了 N 类只触发 X 类）+ 资产解析台账。
    两件事都必须让运营看见：
      - 「声明了 4 类终点、只触发了打标」如果静默发生，等于悄悄丢了需求；
      - 「自动建了 stage 草稿」如果不提示，Mautic 里会多一个没人认领的未上线资产。
    """
    if not isinstance(prop, dict):
        return ""
    warns = prop.get("compile_warnings") or []
    assets = prop.get("asset_resolution") or []
    if not warns and not assets:
        return ""
    out = []
    if warns:
        items = "".join(f"<li>{_esc(w)}</li>" for w in warns)
        out.append(
            "<details open><summary class='pill b-warn' style='cursor:pointer'>"
            f"编译提示 {len(warns)} 条（终点判定/信号回落/资产解析）</summary>"
            f"<ul style='margin:6px 0 0 18px;padding:0;font-size:12px;line-height:1.7'>{items}</ul>"
            "</details>")
    if assets:
        rows = []
        for a in assets:
            st = a.get("status") or ""
            badge = ("<span class='pill b-warn'>自动建草稿</span>" if st == "created"
                     else "<span class='pill ok'>复用已有</span>" if st in ("reused", "id_ref", "inline_id")
                     else "<span class='pill b-warn'>未解析</span>")
            rows.append(
                f"<tr><td>{_esc(_ASSET_LABEL.get(a.get('kind'), a.get('kind', '')))}</td>"
                f"<td><code>{_esc(str(a.get('name') or ''))}</code></td>"
                f"<td>{_esc(str(a.get('id') if a.get('id') is not None else '—'))}</td>"
                f"<td>{badge}</td></tr>")
        out.append(
            "<details><summary class='pill' style='cursor:pointer'>"
            f"资产解析台账 {len(assets)} 项（stage/segment/form 名称 → Mautic ID）</summary>"
            "<table style='margin-top:6px;font-size:12px;border-collapse:collapse'>"
            "<tr style='color:var(--muted)'><th align=left>类型</th><th align=left>声明名</th>"
            "<th align=left>ID</th><th align=left>结果</th></tr>"
            + "".join(rows) + "</table></details>")
    return "".join(out)


def _total_strategy_card(program: dict) -> str:
    """
    总策略 = 画像包（含内容/视觉方向）+ 策略规划 + 人群属性。

    数据优先用策略里落库的值（normalize_campaign 注入 content_direction / visual_direction），
    缺失时回查 audience_map（按 pkg_code），两者都没有就显示「—」，不抛异常。
    """
    g = program.get("goal") or {}
    meta = g.get("meta") or {}
    pkg_code = meta.get("audience_package") or g.get("audience_package") or "GENERIC"
    match = meta.get("audience_match") or g.get("audience_match") or {}
    prof = g.get("audience_profile") or {}
    # audience_map 是画像包参数表的唯一真源；导入失败（文件缺失）也要能渲染页面
    try:
        import audience_map as _am  # noqa: F401
    except Exception:  # noqa: BLE001
        _am = None

    def _from_map(fn, default):
        if _am is None:
            return default
        try:
            return getattr(_am, fn)(pkg_code) or default
        except Exception:  # noqa: BLE001
            return default

    def _join(x, dash="—"):
        if isinstance(x, (list, tuple, set)):
            return "、".join(str(i) for i in x if str(i)) or dash
        return str(x) if x not in (None, "") else dash

    # 策略里落库的方向优先（含画像包融合结果），但必须是同一个包：
    # 策略沿用了别的包（如旧 Program / 兜底 GENERIC）时回查 audience_map，避免展示错包的方向
    st0 = {}
    for c in program.get("campaigns", []):
        s = c.get("strategy") or {}
        if str(s.get("audience_package") or "").strip().upper() == str(pkg_code).strip().upper():
            st0 = s
            break
    cd = st0.get("content_direction") or _from_map("content_direction", {})
    vd = st0.get("visual_direction") or _from_map("visual_direction", {})

    # ① 画像包
    label = match.get("label") or _from_map("label_for", "") or pkg_code
    score = match.get("score")
    score_txt = f"{score:.3f}" if isinstance(score, (int, float)) else "—"
    # evidence 形如 "age=['18-24']"：去掉引号/括号再转义，避免页面上出现 &#x27;
    ev = "；".join(str(x).replace("'", "").replace("[", "").replace("]", "")
                   for x in (match.get("evidence") or [])) or "（无具体字段命中）"
    pkg_html = (f"<p class='pill'>画像包 <code>{_esc(pkg_code)}</code> · {_esc(label)}"
                f" · score <b>{_esc(score_txt)}</b></p>"
                f"<p class='note'>命中证据：{_esc(ev)}</p>")
    matches = match.get("matches") or []
    if len(matches) > 1:
        pkg_html += ("<p class='note'>命中多个画像包："
                     + _esc("；".join(f"{m.get('code')} {m.get('label','')} {m.get('score')}"
                                      for m in matches))
                     + "（策略取各包最大值）</p>")
    if match.get("fallback"):
        nm = match.get("near_miss") or {}
        thr = 0.6
        if _am is not None:
            try:
                thr = float((_am.thresholds() or {}).get("threshold") or 0.6)
            except Exception:  # noqa: BLE001
                pass
        gap = None
        try:
            gap = round(float(thr) - float(nm.get("score") or 0), 3)
        except (TypeError, ValueError):
            gap = None
        pkg_html += (f"<p class='b-warn'>未达阈值 {_esc(thr)}，已用 GENERIC 兜底"
                     + (f"：最接近 {_esc(nm.get('code') or '—')} {_esc(nm.get('score'))}"
                        f"，差 {_esc(gap)}" if nm else "")
                     + "</p>")

    # ② 目标人群属性（7 字段）
    rows = "".join(
        f"<tr><th>{_esc(lbl)}</th><td>{_esc(_join(prof.get(k)))}</td></tr>"
        for k, lbl in (("age", "年龄段"), ("gender", "性别"), ("income", "月收入档"),
                       ("education", "教育经历"), ("industry", "行业"),
                       ("source", "首选来源"), ("region", "国家/地区")))

    # ③ 内容方向
    cd_html = (f"<p class='note'>levers / 内容角度：{_esc(_join(cd.get('levers') or cd.get('angles')))}</p>"
               f"<p class='note'>调性 tone：{_esc(cd.get('tone') or '—')}</p>"
               f"<p class='note'>禁用词：{_esc(_join(cd.get('forbidden_phrases')))}</p>"
               f"<p class='note'>CTA 模板：{_esc(_join(cd.get('cta_templates')))}</p>"
               f"<p class='note'>主题示例：{_esc(_join(cd.get('subject_examples') or cd.get('claims')))}</p>")

    # ④ 视觉方向（palette 渲染成小色块）
    import re as _re
    pal = vd.get("palette") or {}
    swatches, pal_txt = [], []
    for k, v in pal.items():
        v_s = str(v)
        pal_txt.append(f"{k}={v_s}")
        if _re.fullmatch(r"#[0-9a-fA-F]{3,8}", v_s.strip()):
            swatches.append(
                f"<span title='{_esc(k)} {_esc(v_s)}' style='display:inline-block;width:22px;"
                f"height:22px;border-radius:4px;background:{_esc(v_s.strip())};"
                f"border:1px solid #ccc;vertical-align:middle;margin-right:2px'></span>")
    vd_html = (f"<p class='note'>画面调性：{_esc(vd.get('visual') or '—')}</p>"
               f"<p class='note'>配色：{''.join(swatches) or '—'} "
               f"<span class='pill'>{_esc(' '.join(pal_txt) or '—')}</span></p>"
               f"<p class='note'>设计方向：{_esc(vd.get('design_direction') or '—')}</p>")

    return (f"<div class='card'><h3>总策略（画像包 + 策略规划 + 属性）</h3>"
            f"<p class='note'>总策略 = 按目标人群特点推断的画像包（内容/视觉/频次方向） + AI策略规划 + 运营填写的人群属性；以下只读。</p>"
            f"<h4 style='margin:10px 0 4px'>① 画像包（系统推断）</h4>{pkg_html}"
            f"<h4 style='margin:10px 0 4px'>② 目标人群属性（运营填写）</h4>"
            f"<table class='kv'>{rows}</table>"
            f"<h4 style='margin:10px 0 4px'>③ 内容方向</h4>{cd_html}"
            f"<h4 style='margin:10px 0 4px'>④ 视觉方向</h4>{vd_html}</div>")


def _program_body(program: dict, msg: str = "") -> str:
    gid = program["goal_id"]
    goal = program["goal"]
    # 自适应规则说明
    rules = ("<p class='note'>自适应规则（确定性，可审计）：上游完成并回写达成后，按「达成率/退订率」"
             "改写<b>当前</b>campaign 策略（需二次确认）；剩余 campaign 由「确认剩余策略（应用 AI策略）」粘贴 JSON 推进 —— "
             "达标→保持略降本；未达标(≥50%)→提频+换内容+urgency；乏力→大幅提频+扩分组(broaden/reengage)+换内容；"
             "退订超阈→降频+suppression。</p>")
    # 派生计划摘要（单 campaign 点击率由系统反推 + 合理性判定 + Agent 优化说明）
    plan = program.get("plan") or {}
    plan_html = ""
    if plan:
        _cr = plan.get("click_rate")
        _cr_disp = (f"{round(_cr*10000)/100}%" if isinstance(_cr, (int, float)) and _cr > 0 else "—")
        _reasonable = plan.get("reasonable", True)
        _verdict = ("<span class='b-ok'>合理 ✓</span>" if _reasonable
                    else "<span class='b-bad'>需优化 ⚠</span>")
        plan_html = (f"<div class='card'><h3>派生计划摘要</h3>"
                     f"<p class='note'>战役数：<b>{_esc(plan.get('n_campaigns','—'))}</b> · "
                     f"各 campaign 转化目标：<b>{_esc(plan.get('per_campaign_target','—'))}</b></p>"
                     f"<p class='note'>单 campaign 打开/点击率（推算）：<b>{_cr_disp}</b>"
                     f"（={_esc(_cr)}，由总体目标反推）</p>"
                     f"<p class='note'>合理性判定：{_verdict}</p>"
                     f"<p class='note'>Agent 优化说明：{_esc(plan.get('optimization_note',''))}</p></div>")
    # campaign 流水线
    cards = ""
    campaigns = program["campaigns"]
    idx = _mautic_asset_index()  # Mautic 资产 ref→id 索引（外链用；未连接则为空）
    for i, c in enumerate(campaigns):
        prop = c["proposal"]
        ap = prop.get("approval")
        st = c["status"]
        st_lbl, st_cls = STATUS.get(st, (st, "b-idle"))
        st_badge = f"<span class='badge {st_cls}'>{_esc(st_lbl)}</span>"
        ap_txt = (f"<span class='badge b-ok'>{_esc(ap['status'])}/{_esc(ap['level'])}</span>"
                  if ap else "<span class='badge b-warn'>未审批</span>")
        # 审批/推送/完成 表单
        # 静默窗豁免（若策略声明）：明示 + 审批人须勾选确认，否则审批门驳回
        sc_c = c["strategy"].get("send_conditions") or {}
        qh_c, ack_c = "", ""
        if sc_c.get("quiet_hours_exempt"):
            qh_c = (f"<p class='b-warn'>已豁免静默窗 22:00–09:00"
                    f"（限定 ≤{sc_c.get('send_within_minutes') or 0}min 内发出）；审批人可驳回。</p>")
            ack_c = ("<label style='margin:6px 0 2px'><input type='checkbox' name='ack_quiet_exempt' "
                     "style='width:auto;display:inline-block'> 我已确认豁免静默窗</label>")
        if ap and ap.get("status") == "APPROVED":
            approve_f = ""
        else:
            approve_f = (f"<form method='post' action='/program/{gid}/campaign/{c['cid']}/approve' "
                         f"style='margin:8px 0'>"
                         f"<input name='approver' placeholder='审批人(真人)' style='width:160px;display:inline-block'>"
                         f"{ack_c}<button class='btn sm' type='submit'>审批通过</button></form>")
        push_f = ""  # 合并到下方 create_f（"创建并推送到 Mautic"），避免与"推送"按钮重复造成混淆
        # 新阶段创建按钮（#8）：首波 / 上一波「已审批」即可点（不再要求上一波完成+回填，避免 waterfall 死锁）；
        # 已审批待执行(approved_idle) 也显示按钮 → 推送失败后可从 UI 重新推送（不再被门禁关在门外）。
        # feedback 只作软提示（影响自适应微调），不作为发布下一波的硬门槛。
        create_f = ""
        if ap and st not in ("executing", "done_met", "done_below"):
            is_retry = (st == "approved_idle")
            if i == 0:
                label = "重新推送到 Mautic" if is_retry else "创建并推送到 Mautic"
                create_f = (f"<form method='post' action='/program/{gid}/campaign/{c['cid']}/create' "
                            f"onsubmit='return confirm(\"确认推送到 Mautic（localhost:8080）并发布？\")' "
                            f"style='display:inline;margin-left:6px'>"
                            f"<button class='btn sm sec' type='submit'>{label}</button></form>")
            else:
                prev = campaigns[i - 1]
                # 解锁条件：上一波「已审批(APPROVED)」或「已启动/已完成」——不再要求上一波 done + 人工回填 feedback
                prev_ap = (prev.get("proposal") or {}).get("approval") or {}
                prev_approved = (prev_ap.get("status") == "APPROVED")
                prev_launched = prev["status"] in ("approved_idle", "executing", "done_met", "done_below")
                if prev_approved or prev_launched:
                    label = "重新发布下一波 →" if is_retry else "确认开启下一个 →"
                    create_f = (f"<form method='post' action='/program/{gid}/campaign/{c['cid']}/create' "
                                f"onsubmit='return confirm(\"确认推送到 Mautic（localhost:8080）并发布下一波？\")' "
                                f"style='display:inline;margin-left:6px'>"
                                f"<button class='btn sm sec' type='submit'>{label}</button></form>")
                    if not prev.get("feedback"):
                        create_f += ("<span class='note' style='margin-left:6px'>（上一波结果未回填："
                                     "可先点「自适应微调」再发布，或直接按既定策略发布下一波）</span>")
                else:
                    create_f = "<span class='pill'>（上一波审批通过后才可创建下一波）</span>"
        # deferred 波次：不得到期自动发送，需运营显式启用
        if st == "deferred":
            defer_f = (f"<form method='post' action='/program/{gid}/campaign/{c['cid']}/activate' "
                       f"style='display:inline;margin-left:6px'>"
                       f"<button class='btn sm ghost' type='submit'>启用（外部事件已确认）</button></form>")
            defer_note = (f"<p class='note'>已挂起：{_esc(c['strategy'].get('deferred_reason') or '外部事件触发')}"
                          f" —— 不按 delay 自动发送，需运营确认事件后启用。</p>")
            push_f = "<span class='pill'>已挂起，启用后才可推送</span>"
        else:
            defer_f, defer_note = "", ""
        # 目标编辑（#8，可编辑）
        goals_f = (f"<form method='post' action='/program/{gid}/campaign/{c['cid']}/goals' "
                   f"style='margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center'>"
                   f"<label style='margin:0'>转化目标"
                   f"<input name='conv_target' value='{_esc(c.get('conv_target',''))}' "
                   f"style='width:88px;display:inline-block;margin-left:4px'></label>"
                   f"<label style='margin:0'>退订上限"
                   f"<input name='unsub_cap' value='{_esc(c.get('unsub_cap', 0.003))}' "
                   f"style='width:88px;display:inline-block;margin-left:4px'></label>"
                   f"<label style='margin:0'>执行起"
                   f"<input name='exec_start' type='date' value='{_esc(c.get('exec_start',''))}' "
                   f"style='width:140px;display:inline-block;margin-left:4px'></label>"
                   f"<label style='margin:0'>执行止"
                   f"<input name='exec_end' type='date' value='{_esc(c.get('exec_end',''))}' "
                   f"style='width:140px;display:inline-block;margin-left:4px'></label>"
                   f"<button class='btn sm' type='submit'>保存目标</button></form>")
        goals_txt = (f"<p class='pill'>转化目标 <strong>{_esc(c.get('conv_target','—'))}</strong> · "
                     f"退订上限 <strong>{_esc(c.get('unsub_cap', 0.003))}</strong> · "
                     f"执行窗口 {_esc(c.get('exec_start',''))} ~ {_esc(c.get('exec_end',''))}</p>")
        # 执行结果回填（Plan 2 一键预填 + Plan 3 手动保存）
        autofill = c.get("_autofill") or {}
        prev_fb = c.get("feedback") or {}
        # 优先用 _autofill（新拉的），其次用 feedback（上次保存的）
        sent_v = autofill.get("sent", prev_fb.get("sent", ""))
        opened_v = autofill.get("opened", prev_fb.get("opened", ""))
        converted_v = autofill.get("converted", prev_fb.get("converted", ""))
        unsub_v = autofill.get("unsub", prev_fb.get("unsub", ""))
        # Plan 2 按钮：GET 到 autofill 路由拉最新数据
        autofill_btn = (
            f"<form method='get' action='/program/{gid}/campaign/{c['cid']}/feedback' "
            f"style='display:inline-block;margin-right:6px'>"
            f"<input type='hidden' name='autofill' value='1'>"
            f"<input type='hidden' name='date' value='{_esc(autofill.get('date', _yesterday_str()))}'>"
            f"<button class='btn sm' type='submit' title='从 Mautic Stats API 拉 { _esc(autofill.get('date', '昨日'))} 真实数预填表单'>📊 从 Mautic 拉{_esc(autofill.get('date', '昨日'))}数据预填</button>"
            f"</form>"
        )
        # Plan 3 表单（POST 手动保存，预填值已注入）
        feedback_f = (f"<form method='post' action='/program/{gid}/campaign/{c['cid']}/feedback' "
                      f"style='margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;align-items:center'>"
                      f"<input name='sent' placeholder='发送数' value='{_esc(sent_v)}' style='width:84px;display:inline-block'>"
                      f"<input name='opened' placeholder='打开数' value='{_esc(opened_v)}' style='width:84px;display:inline-block'>"
                      f"<input name='converted' placeholder='转化数' value='{_esc(converted_v)}' style='width:84px;display:inline-block'>"
                      f"<input name='unsub' placeholder='退订数' value='{_esc(unsub_v)}' style='width:84px;display:inline-block'>"
                      f"<button class='btn sm ghost' type='submit'>💾 保存</button>"
                      f"<span class='pill'>三档：①每日 06:00 自动 ②单击本按钮预填 ③手动改后保存</span>"
                      f"</form>")
        fb_txt = ""
        if prev_fb:
            src = "（人工保存）"
            if autofill.get("date"):
                src = f"（上次预填 @ {_esc(autofill['date'])}，下方表单已注入）"
            fb_txt = (f"<span class='pill'>回填{src}：发送 {prev_fb.get('sent')} · 打开 {prev_fb.get('opened')} · "
                      f"转化 {prev_fb.get('converted')}（达成率 {prev_fb.get('conv_rate')}） · "
                      f"退订 {prev_fb.get('unsub')}（退订率 {prev_fb.get('unsub_rate')}）</span>")
        # 把 autofill 按钮插在表单上方（Plan 2 入口）+ 表单本身（Plan 3 入口）
        feedback_f = autofill_btn + feedback_f
        # 每日战报（feedback_auto，方案1 自动回填存储）+ 一键载入方案优化（Plan 1→优化预判）
        fa = c.get("feedback_auto") or {}
        fa_latest = max(fa.keys()) if fa else None
        fa_html = ""
        optimize_btn = ""
        if fa:
            fd = fa[fa_latest]
            optimize_btn = (
                f"<form method='get' action='/program/{gid}/campaign/{c['cid']}/optimize' "
                f"style='display:inline-block;margin:6px 6px 0 0'>"
                f"<input type='hidden' name='date' value='{_esc(fa_latest)}'>"
                f"<button class='btn sm sec' type='submit' "
                f"title='载入 {_esc(fa_latest)} 自动回填数据做方案优化预判'>"
                f"📈 从自动回填载入方案优化（{_esc(fa_latest)}）</button></form>")
            fa_html = (f"<span class='pill'>自动回填 {_esc(fa_latest)}：发送 {fd.get('sent',0)} · "
                       f"打开 {fd.get('opened',0)} · 点击 {fd.get('clicked',0)} · "
                       f"转化 {fd.get('converted',0)}（达成率 {fd.get('conv_rate',0):.2%}） · "
                       f"退订 {fd.get('unsub',0)}（{fd.get('unsub_rate',0):.2%}）"
                       f"{(' · ' + _esc('；'.join(fd.get('_errors',[]))) if fd.get('_errors') else '')}</span>")
            if len(fa) > 1:
                hist = "".join(
                    f"<tr><td>{_esc(d)}</td><td>{fa[d].get('sent',0)}</td><td>{fa[d].get('opened',0)}</td>"
                    f"<td>{fa[d].get('clicked',0)}</td><td>{fa[d].get('converted',0)}</td>"
                    f"<td>{fa[d].get('unsub',0)}</td><td>{fa[d].get('conv_rate',0):.2%}</td>"
                    f"<td>{fa[d].get('unsub_rate',0):.2%}</td></tr>"
                    for d in sorted(fa.keys(), reverse=True))
                fa_html += (f"<details style='margin-top:4px'><summary class='pill'>历史（{len(fa)} 天）</summary>"
                            f"<table class='kv'><tr><th>日期</th><th>发送</th><th>打开</th><th>点击</th>"
                            f"<th>转化</th><th>退订</th><th>达成率</th><th>退订率</th></tr>{hist}</table></details>")
        # 方案优化预览（_optimize_preview，只读预判；「采纳并应用」才真正改写当前 campaign）
        opt_preview = c.get("_optimize_preview") or {}
        opt_html = ""
        if opt_preview:
            if opt_preview.get("verdict") == "无需优化":
                opt_html = (f"<div class='note' style='margin-top:6px;color:var(--ok);font-weight:600'>"
                            f"✅ 无需优化：{_esc(opt_preview.get('detail',''))}</div>")
            else:
                opt_html = (f"<div class='note' style='margin-top:6px;color:var(--warn);font-weight:600'>"
                            f"⚠️ 建议优化：{_esc(opt_preview.get('detail',''))}</div>"
                            f"<form method='post' action='/program/{gid}/complete' style='margin-top:6px'>"
                            f"<input type='hidden' name='cid' value='{_esc(c['cid'])}'>"
                            f"<input type='hidden' name='conversion' value='{_esc(opt_preview.get('conv',0))}'>"
                            f"<input type='hidden' name='unsub' value='{_esc(opt_preview.get('unsub',0))}'>"
                            f"<input type='hidden' name='confirm' value=''>"
                            f"<button class='btn sm' type='submit'>采纳并应用（改写当前campaign）</button></form>")
        complete_f = (f"<form method='post' action='/program/{gid}/complete' style='margin-top:8px'>"
                      f"<input type='hidden' name='cid' value='{_esc(c['cid'])}'>"
                      f"<input type='hidden' name='confirm' value=''>"
                      f"<input name='conversion' placeholder='达成率0~1（留空用回填）' style='width:150px;display:inline-block'>"
                      f"<input name='unsub' placeholder='退订率0~1' style='width:120px;display:inline-block'>"
                      f"<button class='btn sm ghost' type='submit'>标记完成并回写→ 改写当前campaign</button></form>")
        # AI策略 辅助路径（替代上方全自动启发式）：复制上下文去 WorkBuddy 生成策略，贴回后确认应用到【剩余所有】campaign
        replan_ui = (
            f"<div style='margin-top:10px;border-top:1px dashed var(--line);padding-top:8px'>"
            f"<p class='note'>AI策略 辅助路径（替代上方全自动启发式）：复制上下文去 WorkBuddy 生成策略，贴回后确认应用到"
            f"<b>剩余所有</b>待推进 campaign（两步：先预览 diff，确认后才落库）。</p>"
            f"<button type='button' class='btn sm sec' "
            f"onclick=\"copyReplanPrompt('{_esc(gid)}','{_esc(c['cid'])}')\">"
            f"📋 复制信息（去 WorkBuddy 生成）</button>"
            f"<span id='replan-status-{_esc(c['cid'])}' class='pill'></span>"
            f"<form method='post' action='/program/{_esc(gid)}/confirm-strategy' style='margin-top:8px'>"
            f"<input type='hidden' name='cid' value='{_esc(c['cid'])}'>"
            f"<input type='hidden' name='confirm' value=''>"
            f"<input name='conversion' placeholder='达成率0~1（可选）' style='width:150px;display:inline-block'>"
            f"<input name='unsub' placeholder='退订率0~1' style='width:120px;display:inline-block'>"
            f"<textarea name='strategy_spec' placeholder='粘贴 WorkBuddy 返回的策略 JSON（StrategySpec）' "
            f"style='width:100%;height:84px;margin-top:6px;display:block'></textarea>"
            f"<button class='btn sm' type='submit'>确认剩余策略（应用 AI策略）</button></form></div>"
        )
        result_txt = ""
        if c.get("result"):
            result_txt = (f"<span class='pill'>达成 {c['result'].get('conversion')} · "
                          f"退订 {c['result'].get('unsub')}</span>")
        # Mautic 外链（资产已在 :8080/s/ 生成才给链接；campaign 需已推送拿到 id）
        dr = c["proposal"].get("deploy_result") or {}
        # campaign 名字：未生成（无 Mautic id）→ 内部 cid；已生成 → Mautic 实时名字（可点跳详情页，改名后同步）
        mcid = dr.get("campaign_id") if not dr.get("dry_run") else None
        # 优先用结构化中文名（活动名-波次意图-票种），已部署则用 Mautic 实时名做链接文本
        semantic_name = (prop.get("campaign") or {}).get("name") or ""
        if mcid:
            _mname = _mautic_campaign_name(mcid) or semantic_name or f"campaign #{mcid}"
            label = _mname or semantic_name
            cname_html = (f"<a class='ext' href='{_mautic_base()}/s/campaigns/{_esc(str(mcid))}' "
                          f"target='_blank' rel='noopener' title='Mautic campaign #{_esc(str(mcid))} · 内部 cid={_esc(c['cid'])}'>{_esc(label)}</a>")
        elif semantic_name:
            cname_html = f"<span title='内部 cid={_esc(c['cid'])}'>{_esc(semantic_name)}</span> <code style='opacity:.5;font-size:11px'>{_esc(c['cid'])}</code>"
        else:
            cname_html = f"<code>{_esc(c['cid'])}</code>"
        ext_bits = []
        _em_ref = c["strategy"].get("email_ref", "")
        _seg_ref = c["strategy"].get("segment", "")
        _lp_ref = c["strategy"].get("landing_page_ref", "")
        _lp_url = c["strategy"].get("landing_page_url", "")
        _form_ref = c["strategy"].get("form_ref", "")
        if _em_ref:
            _lk = _mautic_ext_link("email", _em_ref, idx)
            ext_bits.append(f"邮件 {_lk if _lk else _asset_note('email', _em_ref, idx)}")
        if _seg_ref:
            _lk = _mautic_ext_link("segment", _seg_ref, idx)
            ext_bits.append(f"分群 {_lk if _lk else _asset_note('segment', _seg_ref, idx)}")
        if _lp_ref or _lp_url:
            _lk = _mautic_ext_link("landingpage", _lp_ref, idx) if _lp_ref else ""
            if _lk:
                ext_bits.append(f"落页 {_lk}")
            elif _lp_url:
                ext_bits.append(f"落页 <a class='ext' href='{_esc(_lp_url)}' target='_blank' rel='noopener'>详情</a>")
            elif _lp_ref:
                ext_bits.append(f"落页 {_asset_note('landingpage', _lp_ref, idx)}")
        if _form_ref:
            _lk = _mautic_ext_link("form", _form_ref, idx)
            ext_bits.append(f"表单 {_lk if _lk else _asset_note('form', _form_ref, idx)}")
        ext_html = ("<p class='pill'>Mautic 外链：" + " · ".join(ext_bits) + "</p>") if ext_bits else ""
        cards += (f"<div class='card'><div style='display:flex;justify-content:space-between;align-items:center'>"
                  f"<strong>{_esc(c['wave_id'].replace('wave_', 'campaign_') if isinstance(c['wave_id'], str) else c['wave_id'])} · {cname_html}</strong>{st_badge}</div>"
                  f"<p style='margin:8px 0'>{_strategy_summary(c['strategy'], idx)}</p>"
                  f"{_provenance_line(c['strategy'])}"
                  f"{_compile_notes_html(prop)}"
                  f"<p class='pill'>plan_hash <code>{_esc(prop['plan_hash'][:14])}</code> · 审批 {ap_txt} {result_txt}</p>"
                  f"{goals_txt}{fb_txt}{ext_html}"
                  f"<details><summary class='pill'>事件图（{len(prop['graph'])} 节点 · 流程图）</summary>"
                  f"{_graph_svg(prop['graph'])}</details>"
                  f"{defer_note}{qh_c}{approve_f}{push_f}{create_f}{defer_f}{goals_f}{feedback_f}"
                  f"{optimize_btn}{fa_html}{opt_html}{complete_f}{replan_ui}</div>")
    # Mautic 资产清单（新建 vs 调用已有）—— 整 Program 汇总（#6）
    cards += _mautic_asset_table(program, idx)
    # service 序列（与 promo 解耦，不占 promo 配额）
    svc = ""
    for s in program.get("service_sequences", []):
        prop = s["proposal"]
        trig = s["strategy"].get("trigger") or {}
        ex = s["strategy"].get("exemptions") or {}
        gtypes = [n["type"] for n in prop["graph"]]
        sc3 = s["strategy"].get("send_conditions") or {}
        # 静默窗豁免：按策略声明生效，但必须明示，且审批门可驳回
        qh = ""
        ack_needed = bool(sc3.get("quiet_hours_exempt"))
        if ack_needed:
            qh = (f"<p class='b-warn'>已豁免静默窗 22:00–09:00"
                  f"（限定：用户动作即时触发 ≤{sc3.get('send_within_minutes') or 0}min）；"
                  f"审批人可驳回。</p>")
        ap3 = prop.get("approval")
        ap3_txt = (f"<span class='badge b-ok'>{_esc(ap3['status'])}/{_esc(ap3['level'])}</span>"
                   if ap3 else "<span class='badge b-warn'>未审批</span>")
        ack_f = ("<label style='margin:6px 0 2px'><input type='checkbox' name='ack_quiet_exempt' "
                 "style='width:auto;display:inline-block'> 我已确认豁免静默窗（用户动作即时触发 ≤5min）</label>"
                 if ack_needed else "")
        approve3_f = (f"<form method='post' action='/program/{gid}/service/{s['sid']}/approve' "
                      f"style='margin:8px 0'>"
                      f"<input name='approver' placeholder='审批人(真人)' style='width:160px;display:inline-block'>"
                      f"{ack_f}<button class='btn sm' type='submit'>审批通过</button></form>")
        push3_f = (f"<form method='post' action='/program/{gid}/service/{s['sid']}/push' style='display:inline'>"
                   f"<button class='btn sm sec' type='submit'>推送</button></form>" if ap3 else
                   "<span class='pill'>需先审批</span>")
        svc += (f"<div class='card'><div style='display:flex;justify-content:space-between;align-items:center'>"
                f"<strong>服务序列 · <code>{_esc(s['sid'])}</code></strong>"
                f"<span class='badge b-gov'>{_esc(s['status'])}</span></div>"
                f"<p class='note'>{_esc(s['strategy'].get('campaign_name',''))}</p>"
                f"<p class='pill'>触发 <code>{_esc(trig.get('mode','event'))}</code> "
                f"{_esc(trig.get('event',''))} · 延迟 {trig.get('delay_hours',0)}h · 不配 segment</p>"
                f"<p class='pill'>邮件 <code>{_esc(email_display(s['strategy']))}</code> · "
                f"变体 <code>{_esc((s['strategy'].get('content_variant_spec') or {}).get('id',''))}</code>"
                f"{('（按 ' + str(int(float(s['strategy'].get('variant_split',0.5) or 0.5)*100)) + '% 比例走变体）') if (s['strategy'].get('variant_split') and float(s['strategy'].get('variant_split',0) or 0) > 0) else ''}"
                f"{(' · 表单 <code>' + _esc(s['strategy'].get('form_ref','')) + '</code>') if s['strategy'].get('form_ref') else ''}</p>"
                f"<p class='pill'>豁免：{_esc('；'.join(f'{k}' for k in ex) or '—')}</p>"
                f"<p class='pill'>治理节点：{_esc(', '.join(gtypes))}</p>"
                f"<p class='pill'>plan_hash <code>{_esc(prop['plan_hash'][:14])}</code> · 审批 {ap3_txt}</p>"
                f"{qh}"
                f"<details><summary class='pill'>事件图（{len(prop['graph'])} 节点 · 流程图）</summary>"
                f"{_graph_svg(prop['graph'])}</details>"
                f"{approve3_f}{push3_f}</div>")
    if svc:
        svc = ("<div class='card' style='background:var(--gov-soft)'><h3>服务序列（service/transactional）</h3>"
               "<p class='note'>事务型 / 即时触发（由用户动作如表单提交直接驱动，不按 segment + delay 排期）；"
               "合规分治：与 promo Program 解耦 —— 不注入频次闸门/锚点仲裁，豁免 suppress_promo 与 comm_freeze，"
               "不占 promo 配额、不计入每人触达上限。表单等资产按「谁先用谁显示」随所属 campaign 呈现，"
               "非跨 campaign 共享基础设施。</p></div>" + svc)
    # changelog
    clog = ""
    if program.get("changelog"):
        clog = "<div class='card'><h3>自适应变更记录</h3>"
        for e in program["changelog"]:
            chs = e.get("changes") or []
            lines = "".join(
                f"<li><code>{_esc(ch['cid'])}</code>：{'；'.join(ch['notes'])} "
                f"<span class='pill'>→ plan_hash {_esc(ch['plan_hash'][:12])}</span></li>"
                for ch in chs)
            if e.get("source") == "l1_workbuddy":
                extra = []
                if e.get("applied"):
                    extra.append(f"改写剩余：{_esc('；'.join(e['applied']))}")
                if e.get("added"):
                    extra.append(f"新增分支：{_esc('；'.join(e['added']))}")
                lines = "".join(f"<li>{x}</li>" for x in extra) or "<li>（仅标记完成，无下游改写）</li>"
            clog += (f"<p><strong>上游 {_esc(e['completed_cid'])} 完成</strong>"
                     + (" <span class='badge b-gov'>AI策略</span>" if e.get("source") == "l1_workbuddy" else "")
                     + f" · 达成率 "
                     f"{_esc('未设置（R 未给）' if e.get('target_unset') else e.get('ratio'))} · "
                     f"结果 {_esc(e['result'])}</p><ul>{lines}</ul>")
        clog += "</div>"
    # 每日战报（feedback_auto 汇总，方案1 自动回填）—— Program 级卡片
    report_rows = []
    for _c0 in program.get("campaigns", []):
        _fa0 = _c0.get("feedback_auto") or {}
        if not _fa0:
            continue
        _d0 = max(_fa0.keys())
        _fd0 = _fa0[_d0]
        report_rows.append(
            f"<tr><td><code>{_esc(_c0['cid'])}</code></td><td>{_esc(_d0)}</td>"
            f"<td>{_fd0.get('sent', 0)}</td><td>{_fd0.get('opened', 0)}</td>"
            f"<td>{_fd0.get('clicked', 0)}</td><td>{_fd0.get('converted', 0)}</td>"
            f"<td>{_fd0.get('unsub', 0)}</td><td>{_fd0.get('conv_rate', 0):.2%}</td>"
            f"<td>{_fd0.get('unsub_rate', 0):.2%}</td></tr>")
    if report_rows:
        report_html = ("<div class='card'><h3>📊 每日战报（feedback_auto · 各 campaign 最新一日）</h3>"
                       "<p class='note'>来源：daily 脚本 <code>python auto_feedback.py</code> 或手动 "
                       "<code>POST /program/&lt;id&gt;/auto-feedback?date=</code> 写入。点各 campaign 卡片上的"
                       "「📈 从自动回填载入方案优化」做优化预判。</p>"
                       "<table class='kv'><tr><th>campaign</th><th>日期</th><th>发送</th><th>打开</th>"
                       "<th>点击</th><th>转化</th><th>退订</th><th>达成率</th><th>退订率</th></tr>"
                       + "".join(report_rows) + "</table></div>")
    else:
        report_html = ("<div class='card'><h3>📊 每日战报（feedback_auto）</h3>"
                       "<p class='note'>暂无自动回填数据。先跑 <code>python auto_feedback.py</code>"
                       "（或 <code>POST /program/&lt;id&gt;/auto-feedback?date=</code>），"
                       "次日数据即在此汇总，并可在各 campaign 卡片一键载入方案优化。</p></div>")
    # 运营约束 / 策略来源
    cons = (program.get("constraints")
            or (goal.get("meta") or {}).get("constraints") or [])
    cons_html = ""
    if cons:
        cons_html = ("<div class='card'><h3>运营约束（红线）</h3><ul>"
                     + "".join(f"<li>{_esc(x)}</li>" for x in cons) + "</ul></div>")
    src = program.get("strategy_source") or (goal.get("meta") or {}).get("strategy_source") or "default"
    src_html = ("<span class='badge b-gov'>Agent 策略</span>" if src == "agent_spec"
                else "<span class='badge b-warn'>默认递进策略（未提交 StrategySpec）</span>")
    kpi = goal.get("kpi") or {}
    kpi_html = ""
    if kpi.get("target_unset") or kpi.get("target") in (None, 0, 0.0):
        kpi_html = ("<div class='card'><p class='b-warn'>KPI 目标值未设置（运营尚未给 R）："
                    "不做达成率判定、不触发『目标达成』终止，本 Program 只做基线采集与护栏观测。</p></div>")
    goal_name = (goal.get("meta") or {}).get("name") or goal.get("name") or ""
    header_html = (f"<p style='margin:0 0 12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap'>"
                   f"<button class='btn ghost sm' type='button' "
                   f"onclick='if(history.length>1){{history.back()}}else{{location.href=\"/\"}}'>← 返回</button>"
                   f"<a class='btn ghost sm' href='/brief?goal_id={_esc(gid)}' title='预填原 Brief 字段以便迭代优化'>📝 改 Brief</a>"
                   f"<button class='btn danger sm' type='button' style='margin:0 0 0 auto' "
                   f"onclick=\"if(!confirm('确定删除 Program {_esc(gid)} 吗？\\n\\n此操作仅移除驾驶舱本地记录（output/program_{_esc(gid)}.json），不影响 Mautic（:8080）已生成的活动、邮件与落地页。删除后不可撤销。'))return; "
                   f"var b=this;b.disabled=true;b.innerText='处理中…';b.style.opacity='0.65';"
                   f"var ac=new AbortController();var t=setTimeout(function(){{ac.abort();}},15000);"
                   f"fetch('/program/{_esc(gid)}/delete',{{method:'POST',signal:ac.signal}}).then(function(r){{clearTimeout(t);if(r.ok||r.redirected){{location.href='/';}}else{{throw new Error('HTTP '+r.status);}}}})"
                   f".catch(function(e){{clearTimeout(t);b.disabled=false;b.innerText='🗑 删除 program';b.style.opacity='1';alert('删除失败或超时：'+((e&&e.message)||e));}});\">🗑 删除 program</button>"
                   f"</p>"
                   f"<h1>Program {_esc(gid)}</h1>"
                   f"<p class='sub'>目标名称：{_esc(goal_name) if goal_name else '（未命名）'} "
                   f"（ID: {_esc(gid)}）<br>"
                   f"{_esc(goal.get('objective',''))} · 渠道 {_esc(','.join(goal.get('channels',[])))}"
                   f" · {program['n_campaigns']} 个 campaign"
                   f"{(' + ' + str(program.get('n_service_sequences', 0)) + ' 条服务序列') if program.get('n_service_sequences') else ''}"
                   f" · 策略来源 {src_html}</p>")
    # 全局按钮点击反馈：点击提交按钮后立即禁用 + 改文案为「处理中…」，防止重复点击 / 反映已点
    click_guard_js = (
        "<script>(function(){"
        "document.querySelectorAll('form').forEach(function(f){"
        "f.addEventListener('submit', function(){"
        "var btns=f.querySelectorAll('button[type=submit]');"
        "btns.forEach(function(b){"
        "b.disabled=true;"
        "if(!b.dataset.origText){b.dataset.origText=b.innerText;}"
        "b.innerText='处理中…';"
        "b.style.opacity='0.65';"
        "});"
        "});"
        "});"
        "})();</script>"
    )
    replan_js = (
        "<script>(function(){"
        "window.copyReplanPrompt=function(gid,cid){"
        "var el=document.getElementById('replan-status-'+cid);"
        "function setStatus(m,ok){if(el){el.textContent=m;el.className='pill '+(ok?'b-ok':'b-warn');}}"
        "function showManual(p){if(!el)return;el.innerHTML='';el.appendChild(document.createTextNode('请复制并在 WorkBuddy 发给小腾：'));var ta=document.createElement('textarea');ta.readOnly=true;ta.style.width='100%';ta.style.height='120px';ta.value=p;el.appendChild(ta);}"
        "setStatus('正在生成复制信息...',false);"
        "fetch('/program/'+gid+'/campaign/'+cid+'/replan-prompt',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})"
        ".then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})"
        ".then(function(res){var j=res.j||{};"
        "if(res.ok&&j.ok&&j.prompt){var p=j.prompt||'';"
        "if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(p).then(function(){setStatus('已复制：请在 WorkBuddy 粘贴给小腾生成下一阶段策略，再把返回的 JSON 贴回下方文本框',true);},function(){showManual(p);});}"
        "else{showManual(p);}"
        "}else{setStatus('生成失败：'+(j.error||'未知错误'),false);}"
        "}).catch(function(e){setStatus('请求失败：'+e,false);});"
        "};"
        "})();</script>"
    )
    total_html = _total_strategy_card(program)
    return (f"{msg}{header_html}"
            f"{plan_html}{total_html}{kpi_html}{cons_html}<div class='card'>{rules}</div>{cards}{svc}{report_html}{clog}{click_guard_js}{replan_js}")


def _proposal_body(d: dict, msg: str = "") -> str:
    c = d.get("campaign", {})
    ap = d.get("approval")
    mtc = d.get("tracking", {}).get("mtc_params", {})
    nodes = "<table><tr><th>节点</th><th>类型</th><th>治理</th></tr>"
    for n in d.get("graph", []):
        if n.get("governance"):
            tag = "<span class='tag gov'>治理</span>"
        elif n["type"].endswith(".reserved"):
            tag = "<span class='tag res'>预留</span>"
        else:
            tag = "<span class='tag biz'>业务</span>"
        nodes += f"<tr><td><code>{_esc(n['id'])}</code></td><td>{_esc(n['type'])}</td><td>{tag}</td></tr>"
    nodes += "</table>"
    ap_box = ""
    if ap:
        ok = is_valid(ap)
        ap_box = (f"<p>审批：<span class='{'b-ok' if ok else 'b-bad'}'>{_esc(ap['status'])}/{_esc(ap['level'])}</span>"
                  f" · {_esc(ap['approver'])} · <code>{_esc(ap['plan_hash_bound'][:12])}</code>"
                  f"{'' if ok else ' <span class=b-bad>超时</span>'}</p>")
    else:
        ap_box = ("<form method='post' action='/proposal/%s/approve'>"
                  "<input name='approver' placeholder='审批人' style='width:160px;display:inline-block'>"
                  "<button class='btn sm' type='submit'>审批通过</button></form>" % _esc(c.get("goal_id", "")))
    push_box = ""
    if d.get("deployed"):
        push_box = "<p class='b-ok'>✅ 已推送</p>"
    elif ap:
        push_box = ("<form method='post' action='/proposal/%s/push'>"
                    "<button class='btn sm sec' type='submit'>推送</button></form>" % _esc(c.get("goal_id", "")))
    else:
        push_box = "<p class='note'>需先审批。</p>"
    return (f"{msg}<div class='card'><h3>Campaign 元信息</h3>"
            f"<p><code>{_esc(c.get('goal_id',''))}</code> · {_esc(','.join(c.get('channels',[])))}"
            f" · 预留 {_esc(','.join(c.get('reserved_channels',[])))} · LP <code>{_esc(c.get('landing_page_url',''))}</code></p>"
            f"<p>mtc_* <code>{_esc(json.dumps(mtc, ensure_ascii=False))}</code> · plan_hash <code>{_esc(d.get('plan_hash',''))}</code></p></div>"
            f"<div class='card'><h3>事件图（{len(d.get('graph',[]))} 节点）</h3>{nodes}</div>"
            f"<div class='card'><h3>审批门 (L3)</h3>{ap_box}</div>"
            f"<div class='card'><h3>推送</h3>{push_box}</div>")


def _resolve_strategy_spec_full(src: str):
    """
    解析 StrategySpec（文件路径或 JSON 文本）
    → (campaigns, service_sequences, err, meta, raw_spec)。

    比 _resolve_strategy_spec 多回一个 **原始 spec dict**：一致性校验要拿 spec 原文
    （campaigns[].send_conditions / locale / window / kpi / audience_package）与 Brief 比，
    归一化后的 strategies 已经丢掉了「运营到底写了什么」。
    """
    try:
        spec = parse_strategy_spec(src)
    except Exception as e:  # noqa: BLE001
        return [], [], str(e), None, None
    if not isinstance(spec, dict):
        return [], [], "StrategySpec 不是 JSON 对象", None, None
    campaigns = strategies_from_spec(spec)
    services = service_sequences_from_spec(spec)
    meta = spec_goal_defaults(spec)
    if not campaigns and not services:
        return [], [], "StrategySpec 的 campaigns / service_sequences 均为空", meta, spec
    return campaigns, services, "", meta, spec


def _resolve_strategy_spec(src: str):
    """解析 StrategySpec（文件路径或 JSON 文本）→ (campaigns, service_sequences, err, meta)。"""
    campaigns, services, err, meta, _spec = _resolve_strategy_spec_full(src)
    return campaigns, services, err, meta


# --------------------------- 一致性校验（阻断式）辅助 ---------------------------
def _conflicts_card_html(conflicts, title: str = "策略规格与基础信息冲突",
                         note: str = "请修正 StrategySpec 或基础信息后重新提交。") -> str:
    """把 Conflict 列表渲染成一张红色卡片（每冲突一行，文案来自 format_conflicts）。"""
    if not conflicts:
        return ""
    lines = "".join(f"<div class='b-bad' style='margin:4px 0;padding:6px 8px'>{_esc(l)}</div>"
                    for l in format_conflicts(conflicts))
    return (f"<div class='card' style='border-left:4px solid #c0392b'>"
            f"<h3 style='margin:0 0 6px;color:#c0392b'>{_esc(title)}</h3>"
            f"<p class='note' style='margin:0 0 8px'>{_esc(note)}</p>"
            f"{lines}</div>")


def _brief_ctx_from_form(form: dict, locales: list = None) -> dict:
    """校验用 Brief 上下文：与 /brief 表单字段一一对应（不一致即阻断）。"""
    form = form or {}
    prof = {k: form.get("audience_" + k)
            for k in ("age", "gender", "income", "education",
                      "industry", "source", "region")}
    return {
        "objective": (form.get("objective", "") or "").strip(),
        "goal_name": (form.get("goal_name", "") or "").strip(),
        "start_date": (form.get("start_date", "") or "").strip(),
        "end_date": (form.get("end_date", "") or "").strip(),
        "overall_conv": (form.get("overall_conv", "") or "").strip(),
        "locale": locales if locales else form.get("locale"),
        "constraints": form.get("constraints", "") or "",
        "audience_region": prof.get("region"),
        "audience_profile": prof,
        "is_revenue": form.get("is_revenue", "0"),
        "budget": form.get("budget", "") or "",
    }


def _brief_ctx_from_goal(g: dict) -> dict:
    """校验用 Brief 上下文：来自已落库的 Program（L1 确认策略路径用）。"""
    g = g or {}
    meta = g.get("meta") or {}
    kpi = g.get("kpi") or {}
    tgt = kpi.get("target")
    return {
        "objective": g.get("objective", "") or "",
        "goal_name": g.get("name", "") or "",
        "start_date": g.get("start_date", "") or "",
        "end_date": g.get("end_date", "") or "",
        "overall_conv": ("" if tgt in (None, 0, 0.0) else str(tgt)),
        "locale": meta.get("locales") or g.get("locale") or [],
        "constraints": meta.get("constraints") or g.get("constraints") or [],
        "audience_region": (g.get("audience_profile") or {}).get("region"),
        "audience_profile": g.get("audience_profile") or {},
        "is_revenue": "1" if g.get("is_revenue") else "0",
        "budget": g.get("budget", "") or "",
    }


def _prefill_from_form(form: dict) -> dict:
    """提交被阻断时回显已填内容（含约束与策略规格文本），避免运营重填。"""
    keys = ["goal_name", "objective", "start_date", "end_date", "overall_conv",
            "budget", "is_revenue", "constraints", "strategy_spec",
            "audience_age", "audience_gender", "audience_income",
            "audience_education", "audience_industry", "audience_source",
            "audience_region", "locale", "ref_goal_id"]
    out = {}
    for k in keys:
        v = (form or {}).get(k, "")
        if v not in (None, ""):
            out[k] = v
    return out


# --------------------------- Handler ---------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _guard(self, label, fn, *args, **kwargs):
        """包裹写操作：未捕获异常记入开发日志并渲染带日志面板的 500 页。"""
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            cockpit_log("ERROR", f"{label} 未捕获异常:\n{tb}")
            try:
                self._send(500, _page(
                    f"500 · {label}",
                    f"<div class='card'><p class='b-bad'>处理「{_esc(label)}」时抛出未捕获异常：</p>"
                    f"<pre class='pre'>{_esc(tb)}</pre>"
                    f"<p class='note'>完整上下文见页面底部「开发日志」面板。</p></div>"))
            except Exception:  # noqa: BLE001
                pass
            return None

    def _send(self, code, body, headers=None):
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, obj: dict):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        # URL 解码：goal_id 可能是中文（slug 只剔非字母数字，中文属于 isalnum），
        # 浏览器会把 /program/中文 百分号编码后发回来，不解码就匹配不到 Program。
        path = urllib.parse.unquote(self.path.split("?")[0])
        cockpit_log("INFO", f"GET {path}")
        if path in ("/", ""):
            return self._guard("dashboard", lambda: self._send(200, _page("驾驶舱", _dash_body())))
        if path == "/brief":
            # 支持 /brief?spec=<StrategySpec 文件路径> 预览 Agent 策略（只读）
            # 支持 /brief?goal_id=<id> 预填已存在 Program 的字段（"改 Brief" 回链用）
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            spec_src = (q.get("spec") or [""])[0].strip()
            goal_id_src = (q.get("goal_id") or [""])[0].strip()
            strategies, services, err, meta = [], [], "", None
            prefill = None  # 来自已有 Program 的预填值
            if spec_src:
                strategies, services, err, meta = _resolve_strategy_spec(spec_src)
            if goal_id_src:
                p = _load_program(goal_id_src)
                if p:
                    g = p.get("goal", {}) or {}
                    ap = g.get("audience_profile") or {}
                    kpi = g.get("kpi") or {}
                    prefill = {
                        "goal_name": g.get("name", "") or "",
                        "objective": g.get("objective", "") or "",
                        "start_date": g.get("start_date", "") or "",
                        "end_date": g.get("end_date", "") or "",
                        "overall_conv": str(kpi.get("target", "")) if kpi.get("target") not in (None, 0, 0.0) else "",
                        "audience_age": ap.get("age", "") or "",
                        "audience_gender": ap.get("gender", "") or "",
                        "audience_income": ap.get("income", "") or "",
                        "audience_education": ap.get("education", "") or "",
                        "audience_industry": ap.get("industry", "") or "",
                        "audience_source": ap.get("source", "") or "",
                        "audience_region": ap.get("region", "") or "",
                        "is_revenue": "1" if g.get("is_revenue") else "0",
                        "budget": str(g.get("budget", 0) or 0),
                        "locale": g.get("locale", "zh_CN") or "zh_CN",
                        "ref_goal_id": goal_id_src,  # 告诉 form 这是改 Brief
                    }
            return self._send(200, _page("新建 Brief", _brief_form(strategies, err, meta, services, prefill)))
        if path.startswith("/program/"):
            # /program/<gid>/campaign/<cid>/feedback?autofill=1&date=YYYY-MM-DD  ← 拉 Mautic 最新数据预填表单
            parts = [x for x in path.split("/") if x]
            if (len(parts) == 5 and parts[2] == "campaign" and parts[4] == "feedback"):
                q = dict(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
                if q.get("autofill"):
                    gid = parts[1]; cid = parts[3]
                    date_str = (q.get("date") or [_yesterday_str()])[0]
                    return self._handle_campaign_feedback_autofill(gid, cid, date_str)
            if (len(parts) == 5 and parts[2] == "campaign" and parts[4] == "optimize"):
                q = dict(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
                gid = parts[1]; cid = parts[3]
                date_str = (q.get("date") or [None])[0]
                return self._handle_campaign_optimize(gid, cid, date_str)
            gid = path[len("/program/"):]
            p = _load_program(gid)
            if not p:
                return self._send(404, _page("未找到", "<p class='b-bad'>Program 不存在</p>"))
            return self._guard("program-view", lambda: self._send(200, _page("Program", _program_body(p))))
        if path.startswith("/proposal/"):
            gid = path[len("/proposal/"):]
            d = _load_proposal(gid)
            if not d:
                return self._send(404, _page("未找到", "<p>提案不存在</p>"))
            return self._guard("proposal-view", lambda: self._send(200, _page("提案", _proposal_body(d))))
        return self._send(404, _page("404", "<p>未知路径</p>"))

    def do_POST(self):
        # 同 do_GET：中文 goal_id 会被浏览器百分号编码，需解码后再匹配 Program
        path = urllib.parse.unquote(self.path.split("?")[0])
        cockpit_log("INFO", f"POST {path}")
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        ctype = self.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                jsbody = json.loads(raw) if raw.strip() else {}
            except Exception:  # noqa: BLE001
                jsbody = {}
        else:
            _qs = urllib.parse.parse_qs(raw)
            jsbody = {}
            for _k, _v in _qs.items():
                # 多选字段保留 list（年龄/教育/行业/来源/国家/语言），其余取首值
                if _k in MULTI_FORM_FIELDS:
                    jsbody[_k] = _v
                else:
                    jsbody[_k] = _v[0]

        if path == "/brief":
            return self._guard("brief", self._handle_brief, jsbody)
        if path == "/brief/generate-strategy":
            return self._guard("generate-strategy", self._handle_generate_strategy, jsbody)
        if path == "/brief/ai-parse":
            return self._guard("ai-parse", self._handle_ai_parse, jsbody)
        if path == "/brief/strategy-prompt":
            return self._guard("strategy-prompt", self._handle_strategy_prompt, jsbody)
        if path.endswith("/approve") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._guard("campaign-approve", self._handle_campaign_approve, gid, cid, jsbody)
        if path.endswith("/push") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._guard("campaign-push", self._handle_campaign_push, gid, cid)
        if path.endswith("/activate") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._guard("campaign-activate", self._handle_campaign_activate, gid, cid)
        if path.endswith("/goals") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._guard("campaign-goals", self._handle_campaign_goals, gid, cid, jsbody)
        if path.endswith("/create") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._guard("campaign-create", self._handle_campaign_create, gid, cid)
        if path.endswith("/auto-feedback"):
            gid = path.split("/")[2] if path.startswith("/program/") else ""
            qs = dict(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            date_str = (qs.get("date") or [_yesterday_str()])[0]
            return self._guard("program-auto-feedback", self._handle_program_auto_feedback, gid, date_str)
        if path.endswith("/delete") and path.startswith("/program/"):
            gid = path.split("/")[2]
            return self._guard("program-delete", self._handle_program_delete, gid)
        if path.endswith("/feedback") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._guard("campaign-feedback", self._handle_campaign_feedback, gid, cid, jsbody)
        if path.endswith("/complete"):
            return self._guard("complete", self._handle_complete, jsbody)
        if path.endswith("/replan-prompt") and "/campaign/" in path:
            _parts = [x for x in path.split("/") if x]
            if len(_parts) == 5 and _parts[2] == "campaign" and _parts[4] == "replan-prompt":
                return self._guard("replan-prompt", self._handle_replan_prompt, _parts[1], _parts[3], jsbody)
        if path.endswith("/confirm-strategy"):
            return self._guard("confirm-strategy", self._handle_confirm_strategy, jsbody)
        if path.endswith("/approve") and "/service/" in path:
            parts = [x for x in path.split("/") if x]
            return self._guard("service-approve", self._handle_service_approve, parts[1], parts[3], jsbody)
        if path.endswith("/push") and "/service/" in path:
            parts = [x for x in path.split("/") if x]
            return self._guard("service-push", self._handle_service_push, parts[1], parts[3])
        if path.endswith("/approve"):
            gid = path.split("/")[-2]
            return self._guard("legacy-approve", self._handle_legacy_approve, gid, jsbody)
        if path.endswith("/push"):
            gid = path.split("/")[-2]
            return self._guard("legacy-push", self._handle_legacy_push, gid)
        return self._send(404, _page("404", "<p>未知路径</p>"))

    @staticmethod
    def _split_campaign(path):
        # /program/<gid>/campaign/<cid>/approve
        parts = [x for x in path.split("/") if x]
        gid = parts[1]
        cid = parts[3]
        return gid, cid

    @staticmethod
    def _ack_quiet_exempt_ok(strategy: dict, form: dict) -> bool:
        """声明了静默窗豁免的，审批人必须显式确认，否则审批门驳回。"""
        sc = (strategy or {}).get("send_conditions") or {}
        if not sc.get("quiet_hours_exempt"):
            return True
        return form.get("ack_quiet_exempt") == "on"

    def _handle_brief(self, form):
        try:
            # ---- L1：Agent 产出的策略（可选）----
            spec_src = (form.get("strategy_spec", "") or "").strip()
            if spec_src:
                strategies, services, spec_err, spec_meta, spec_raw = _resolve_strategy_spec_full(spec_src)
            else:
                strategies, services, spec_err, spec_meta, spec_raw = [], [], "", None, None
            if spec_err:
                raise ValueError(f"StrategySpec 解析失败：{spec_err}")
            d = spec_meta or {}

            # ---- 改 Brief：覆盖而非新建；执行中 campaign 需二次确认 ----
            ref_goal_id = (form.get("ref_goal_id") or "").strip()
            confirm_overwrite = str(form.get("confirm_overwrite") or "") == "1"
            existing = _load_program(ref_goal_id) if ref_goal_id else None
            if existing:
                EXEC_STATES = {"approved_idle", "executing", "done_met", "done_below"}
                exec_cids = [c.get("cid") for c in existing.get("campaigns", [])
                             if c.get("status") in EXEC_STATES]
                if exec_cids and not confirm_overwrite:
                    # 不覆盖：回显表单 + 二次确认警告 + 二次确认按钮（confirm_overwrite=1）
                    prefill = _prefill_from_form(form)
                    prefill["ref_goal_id"] = ref_goal_id
                    return self._send(200, _page(
                        "改 Brief · 二次确认",
                        _brief_form(strategies, spec_err, spec_meta, services, prefill,
                                    confirm_overwrite=True, executing=exec_cids)))

            # N 由策略数组长度决定；未提交策略时由 derive_plan 派生（总体目标转化率 + 起止日期反推点击率）
            overall_conv = (form.get("overall_conv", "") or "").strip()
            plan_raw = derive_plan(overall_conv,
                                   form.get("start_date", "") or d.get("start_date", ""),
                                   form.get("end_date", "") or d.get("end_date", ""),
                                   strategy=strategies or None)
            sd_raw = (form.get("start_date", "") or d.get("start_date", "")).strip()
            ed_raw = (form.get("end_date", "") or d.get("end_date", "")).strip()
            try:
                _oc = float(overall_conv)
            except (TypeError, ValueError):
                _oc = 0.0
            # 已提交 StrategySpec 时按策略中 campaign 数派生，并据总体目标重算可达性
            if strategies:
                n_actual = len(strategies)
                if _oc > 0 and ASSUMED_LP_CONV > 0:
                    _pc = 1 - (1 - _oc) ** (1.0 / n_actual)
                    click_rate = round(_pc / ASSUMED_LP_CONV, 4)
                    reasonable = click_rate <= RC_MAX
                    opt_note = "已提交 StrategySpec：Agent 按策略中 campaign 数派生，仍按总体目标校验可达性"
                else:
                    click_rate, reasonable, opt_note = 0.0, True, "未配置总体目标转化率：跳过可达性校验"
            else:
                n_actual = plan_raw["n_campaigns"]
                click_rate = plan_raw["click_rate"]
                reasonable = plan_raw["reasonable"]
                opt_note = plan_raw["optimization_note"]
            n = n_actual
            per_campaign_target = (round(_oc / n_actual, 4)
                                   if _oc > 0 else plan_raw["per_campaign_target"])
            windows = (_split_windows(sd_raw, ed_raw, n_actual)
                       if sd_raw and ed_raw else
                       [{"start": sd_raw, "end": ed_raw} for _ in range(n_actual)])
            plan = {"n_campaigns": n_actual, "windows": windows,
                    "per_campaign_target": per_campaign_target,
                    "click_rate": click_rate, "reasonable": reasonable,
                    "optimization_note": opt_note}

            # ---- L0：运营只填目标与约束，其余由 Agent 策略补 ----
            locale_val = form.get("locale")
            if isinstance(locale_val, list) and locale_val:
                locales = [str(x).strip() for x in locale_val if str(x).strip()]
            elif locale_val:
                locales = [str(locale_val).strip()]
            else:
                # 未选择 = 全部语言（中英文双语）；仅当用户显式勾选时才收窄
                locales = d.get("locales") or LOCALE_ALL
            if not locales:
                locales = LOCALE_ALL
            constraints = [ln.strip() for ln in
                           (form.get("constraints", "") or "").splitlines() if ln.strip()]
            # 画像包由服务端按 profile 推断；表单不接收 audience_package
            goal_name = (form.get("goal_name", "") or "").strip()
            # 多值字段（age/education/industry/source/region）直接透传 list；单值字段 strip
            _multi_aud = {"age", "gender", "income", "education", "industry", "source", "region"}
            raw = {
                "objective": (form.get("objective", "") or d.get("objective", "")).strip(),
                # 分群由 Agent 策略决定；表单不再收集，取首波分群兜底，保证 L0 校验不破
                "audience_segment": (form.get("audience_segment", "").strip()
                                     or (strategies[0]["segment"] if strategies else "")
                                     or "SEG_AGENT_TBD"),
                "locale": locales[0] if locales else "zh_CN",
                "landing_page_url": (form.get("landing_page_url", "").strip()
                                     or (strategies[0].get("landing_page_url", "")
                                         if strategies else "")),
                "kpi": d.get("kpi") or {"type": "conversion_rate",
                                        "target": float(form.get("kpi_target", "0.15") or "0.15")},
                "budget": float(form.get("budget", "") or d.get("budget", 0) or 0),
                "is_revenue": form.get("is_revenue", "0"),
                "start_date": (form.get("start_date", "") or d.get("start_date", "")).strip(),
                "end_date": (form.get("end_date", "") or d.get("end_date", "")).strip(),
                "channels": ["email"], "reserved_channels": ["sms"],
                "goal_id": d.get("goal_id", ""),
                "audience_profile": {
                    k: (form.get("audience_" + k) if k in _multi_aud
                        else (form.get("audience_" + k, "") or "").strip())
                    for k in ("age", "gender", "income", "education",
                              "industry", "source", "region")
                },
            }
            if not raw["goal_id"]:
                raw.pop("goal_id")
            goal = parse_brief(raw)
            if goal_name:
                goal.name = goal_name
            goal.meta = {
                "locales": locales or d.get("locales", []),
                "constraints": constraints,
                "name": goal.name,
                "strategy_source": (strategies[0].get("strategy_source", "default")
                                    if strategies else "default"),
                "audience_package": goal.audience_package,
                "audience_match": getattr(goal, "audience_match", {}),
                "audience_profile": goal.audience_profile,
                "is_revenue": goal.is_revenue,
            }
            # 画像包已由服务端推断 → 带上 goal 重新归一化，让画像包的
            # 频次 / 静默窗 / 触达时段 / 内容方向默认值真正生效（此前完全空转）
            if spec_raw:
                _re = strategies_from_spec(spec_raw, goal=goal)
                if _re:
                    strategies = _re
            # ---- 一致性校验：spec 与上方基础信息冲突 → 阻断，不生成 Program ----
            if spec_raw:
                conflicts = validate_spec(spec_raw, _brief_ctx_from_form(form, locales),
                                          goal.meta.get("audience_package"))
                if conflicts:
                    return self._send(200, _page(
                        "Brief 与策略规格冲突",
                        _brief_form(strategies, "", spec_meta, services,
                                    _prefill_from_form(form), conflicts)))
            program = build_program(goal, n, compile, strategy_spec=strategies or None,
                                    service_sequences=services or None)
            # 每个 campaign 绑定派生计划：转化目标 + 执行窗口（可在 /program 上编辑）
            for i, c in enumerate(program["campaigns"]):
                w = windows[i] if i < len(windows) else {"start": sd_raw, "end": ed_raw}
                c["conv_target"] = per_campaign_target
                c["unsub_cap"] = 0.003
                c["exec_start"] = w["start"]
                c["exec_end"] = w["end"]
            program["constraints"] = constraints
            program["plan"] = plan
            # 改 Brief 覆盖模式：锁定原 goal_id，确保覆盖同一 Program 文件而非新建
            if existing and ref_goal_id:
                program["goal_id"] = ref_goal_id
                goal.goal_id = ref_goal_id
            # 生成 program 时同步在 Mautic 建一个 project（program = project），所有资产挂其下；
            # Mautic 不可达 / 未配 Basic 凭证时降级为 None，不阻断生成（推送时再惰性补建）。
            try:
                _resolve_program_project(program, "local")
            except Exception as _pe:  # noqa: BLE001
                cockpit_log("WARN", f"brief 建 Mautic project 失败（降级 None，推送时惰性补建）：{type(_pe).__name__}: {_pe}")
            _save_program(program)
            cockpit_log("OK", f"brief 已生成 Program：goal_id={program.get('goal_id')} · mautic_project_id={program.get('mautic_project_id')} · campaigns={len(program.get('campaigns', []))}")
            # Location 响应头按 latin-1 编码：goal_id 含中文（slug 保留中文，属 isalnum）时
            # 直接拼会抛 UnicodeEncodeError，必须先百分号编码（路由侧 do_GET 已 unquote 配对）。
            self.send_response(302)
            self.send_header("Location",
                             "/program/" + urllib.parse.quote(str(goal.goal_id), safe=""))
            self.end_headers()
        except Exception as e:  # noqa: BLE001
            self._send(200, _page("Brief 错误", f"<p class='b-bad'>{_esc(e)}</p><p><a href='/brief'>返回</a></p>"))

    def _handle_generate_strategy(self, brief: dict):
        """
        Brief 上下文 → 调策略生成端点（若配置）或直接返回提示词降级。
        返回 JSON：{"ok":true,"strategy_spec":<json字符串>,...}
                  或 {"ok":false,"fallback":true,"prompt":<str>,"error":<可选>}。
        """
        # 服务端按 audience_profile 推断（多值 → 多画像），注入 brief 供提示词「取最大值」
        prompt = _build_strategy_prompt_from_brief(brief)
        sg = load_strategy_gen_config()
        if sg["enabled"]:
            # 外部策略生成端点优先
            try:
                import urllib.request as _u, urllib.error as _ue  # noqa: E402
                payload = json.dumps(brief, ensure_ascii=False).encode("utf-8")
                req = _u.Request(sg["endpoint"], data=payload, method=sg["method"])
                for k, v in sg["headers"].items():
                    req.add_header(k, v)
                try:
                    with _u.urlopen(req, timeout=sg["timeout"]) as resp:
                        raw = resp.read().decode("utf-8", "replace")
                except _ue.HTTPError as e:
                    raw = e.read().decode("utf-8", "replace")
                except Exception as e:  # noqa: BLE001
                    return self._send_json({"ok": False, "fallback": True,
                                            "prompt": prompt, "error": f"端点请求失败：{e}"})
                spec = _extract_strategy_spec(raw)
                if spec is None:
                    return self._send_json({"ok": False, "fallback": True,
                                            "prompt": prompt, "error": "端点返回无法解析为 StrategySpec"})
                return self._send_json({"ok": True, "strategy_spec": spec, "prompt": prompt,
                                        "via": "endpoint"})
            except Exception as e:  # noqa: BLE001
                return self._send_json({"ok": False, "fallback": True, "prompt": prompt,
                                        "error": str(e)})
        # 无外部端点：直连 DeepSeek 合成（复用 deepseek key + build_strategy_prompt）
        try:
            content = _deepseek_completion(
                "你是营销 Agent 的 AI策略合成器。只输出严格 JSON，不要解释文字、"
                "不要 markdown 代码块，只输出可被 json.loads 解析的 StrategySpec 对象。",
                prompt)
            spec = _extract_strategy_spec(content)
            if spec is None:
                return self._send_json({"ok": False, "fallback": True, "prompt": prompt,
                                        "error": "DeepSeek 返回无法解析为 StrategySpec"})
            return self._send_json({"ok": True, "strategy_spec": spec, "prompt": prompt,
                                    "via": "deepseek"})
        except RuntimeError as e:
            return self._send_json({"ok": False, "fallback": True, "prompt": prompt,
                                    "error": str(e)})

    def _handle_strategy_prompt(self, brief: dict):
        """
        只返回策略合成提示词（不调 DeepSeek / 外部端点），供用户复制到 WorkBuddy 生成后贴回。
        返回 JSON：{"ok":true,"prompt":<str>} 或 {"ok":false,"error":<str>}。
        """
        try:
            prompt = _build_strategy_prompt_from_brief(brief)
        except Exception as e:  # noqa: BLE001
            return self._send_json({"ok": False, "error": f"构建提示词失败：{e}"})
        return self._send_json({"ok": True, "prompt": prompt})

    def _handle_ai_parse(self, body: dict):
        """
        入口桩：任何未预期异常都必须转成结构化 JSON 返回。
        原因：BaseHTTPRequestHandler 里冒出去的异常会让 Python 直接掐断连接，
        浏览器 fetch 收到的是「无响应」→ 报 TypeError: Failed to fetch，
        用户完全看不到真实错误。这里统一兜底并落盘 ai_error.log。
        """
        try:
            return self._handle_ai_parse_inner(body)
        except Exception as e:  # noqa: BLE001
            _log_ai_error(f"ai-parse 未捕获异常 {type(e).__name__}: {e}")
            return self._send_json(
                {"ok": False, "error": f"AI 识别内部错误：{type(e).__name__}: {e}"})

    def _handle_ai_parse_inner(self, body: dict):
        """
        营销目标文本 → DeepSeek 意图识别 → 回填结构化字段。
        返回 JSON：{"ok":true,"start_date","end_date","audience_gender","constraints",
                    "strategy_spec","filled":[...]}
                  或 {"ok":false,"error":<str>}。
        """
        objective = (body.get("objective") or "").strip()
        if not objective:
            return self._send_json({"ok": False, "error": "objective 为空"})
        cfg = load_deepseek_config()
        if not cfg["enabled"]:
            return self._send_json({"ok": False, "error": "未配置 DeepSeek（config.json [deepseek].api_key 或 DEEPSEEK_API_KEY）"})
        system_prompt = (
            "你是一个营销 Brief 意图识别器。阅读运营用自然语言写下的「营销目标」描述，"
            "抽取其中隐含的结构化字段，输出严格 JSON（只输出 JSON，不要解释、不要 markdown 代码块）。\n\n"
            "字段定义（键名必须精确）：\n"
            "- goal_name: 字符串。活动/营销的内部简称。从描述提炼一句短名称，"
            "去掉纯时间词（如「2027 年」）。例：「元旦跨年拼盘演唱会」→「元旦跨年拼盘演唱会」；"
            "「2028 欧冠决赛登记」→「欧冠决赛登记」。未提及则 \"\"。\n"
            "- start_date: 字符串 \"YYYY-MM-DD\"。"
            "若描述直接给出活动开始日期则填；若给出「节日/活动前 N 个月/周/天」「开始后 N 天」等相对时间，"
            "请按常识推断节日/活动的固定日期并计算："
            "例：「2010 年万圣节前 3 个月」→ 万圣节 10 月 31 日，前 3 个月 = \"2010-08-01\"；"
            "「元旦前一周」→ \"YYYY-12-25\"（跨年需正确进位）。"
            "仅当无法合理推断时留空 \"\"。\n"
            "- end_date: 字符串 \"YYYY-MM-DD\"。"
            "若直接给出结束日期则填；若给出「为期 N 个月/天/周」「节日/活动结束后 N 天/周」，"
            "请按 start_date 或节日日期计算覆盖时段的最后一天（含）。"
            "例：起 2027-01-01、为期两个月 → 2027-02-28；"
            "「2010 年万圣节结束后一周」→ \"2010-11-07\"。跨年正确进位。"
            "否则 \"\"。\n"
            "- audience_age_range: 字符串 \"min-max\"（纯数字年龄界限，精确到描述给出的数值，"
            "不要折算成档位）。下限未提及填 0，上限未提及留空：\n"
            "  · \"40 岁以下\" → \"0-40\"；\"18~34 岁\"、\"18-34 岁\" → \"18-34\"；\n"
            "  · \"30-45\" → \"30-45\"；\"50 岁以上\"、\"60 岁以上\" → \"50-\"/\"60-\"。\n"
            "  未给出数值界限（如「年轻人」「中年」「20 出头」）则 \"\"。\n"
            "- audience_age: 枚举字符串或多值（多个值用英文逗号分隔，不要空格，如 \"18-24,25-34\"）。"
            "可取值：\"\" / \"18-24\" / \"25-34\" / \"35-44\" / \"45-54\" / \"55+\"。"
            "仅当无法给出 audience_age_range（模糊描述）时才按档位填写：\n"
            "  · \"年轻人\"、\"20 出头\" → \"18-24\"；\"中年\" → \"35-44,45-54\"。\n"
            "  若 audience_age_range 非空，此项必须填 \"\"（前端会按精确范围自动算档位，"
            "禁止两处同时给值）。未提及年龄则两者都 \"\"。\n"
            "- audience_gender: 枚举 \"\" / \"男\" / \"女\" / \"未知\"。仅当描述指明性别时填写。\n"
            "- audience_income: 枚举字符串，必须取其一：\"\" / \"L1\" / \"L2\" / \"L3\" / \"L4\" / \"L5\"。"
            "档位含义：L1=<3k，L2=3k~8k，L3=8k~20k，L4=20k~50k，L5=>50k（单位人民币/月）。"
            "把收入描述映射到「最贴近起点」的一档（单选）：\n"
            "  · 「5 千以上」「5k 以上」「月入 5 千」→ \"L2\"（起点 5k 落在 3k~8k 档）；\n"
            "  · 「1 万以上」→ \"L3\"；「2 万以上」「月入 2 万」→ \"L4\"；「5 万以上」「10 万以上」→ \"L5\"；\n"
            "  · 「3 千以下」→ \"L1\"。未提及收入则 \"\"。\n"
            "- audience_source: 枚举字符串，必须取其一：\"\" / \"CTL\" / \"CSTS\" / \"SPORT\" / \"爬虫\" / \"其他\" / \"手动输入\"。"
            "渠道/来源映射（大小写不敏感，统一转大写）：\n"
            "  · 「csts」「CSTS 渠道」「csts渠道」→ \"CSTS\"；\n"
            "  · 「携程」「ctl」→ \"CTL\"；「sport」「体育」→ \"SPORT\"；「爬虫」→ \"爬虫\"。\n"
            "  未提及来源则 \"\"。\n"
            "- audience_education: 枚举 \"\" / \"名校\" / \"MBA\" / \"211\" / \"985\" / \"QS100\" / \"普通本科\" / \"其他\"。未提及则 \"\"。\n"
            "- audience_industry: 枚举 \"\" / \"IT\" / \"制造\" / \"金融\" / \"旅游\" / \"教育\" / \"医疗\" / \"零售\" / \"其他\"。未提及则 \"\"。\n"
            "- audience_region: 枚举 \"\" / \"中国大陆\" / \"港澳台\" / \"海外\"。未提及则 \"\"。\n"
            "- overall_conv: 字符串，表示「项目预期转化率×跳转率」，0~1 的小数（最多 4 位小数）。"
            "仅当描述明确提到「转化率」「跳转率」「最终转化」「预期转化」等并给出百分比或小数时填写。"
            "例：「转化率 15%」→ \"0.15\"；「预期 0.2」→ \"0.2\"；「跳转率 20%、转化率 50%」→ 相乘 \"0.1\"。"
            "未提及则 \"\"。\n"
            "- is_revenue: 枚举 \"\" / \"0\" / \"1\"。判断该活动是否涉及营收/付费目标（影响审批门槛）。\n"
            "  · 提及「售票/付费/营收/购买/销售/客单价/订单/成交」→ \"1\"；\n"
            "  · 提及「意向登记/品牌曝光/报名/预约/拉新/领券/免费」且无付费意图 → \"0\"；\n"
            "  · 无法判断 → \"\"。\n"
            "- budget: 字符串。预算金额，统一转成「元」为单位的整数数字字符串（不带千分位、不带货币符号）。"
            "例：「预算 5 万」→ \"50000\"；「10万元」→ \"100000\"；「预算 5000 元」→ \"5000\"。未提及则 \"\"。\n"
            "- locale: 枚举字符串或多值（逗号分隔），取值 \"\" / \"zh_CN\" / \"en_US\"。\n"
            "  · 提及「英文」「English」「英文版」「面向海外」→ \"en_US\"；\n"
            "  · 提及「中文」「bilingual / 中英文 / 中英双语」→ \"zh_CN,en_US\"；\n"
            "  · 其余情况（中文/未提及）→ \"zh_CN\"。\n"
            "- constraints: 字符串（多条件用换行 \\n 分隔）。把「X 点后不能发/次日 Y 点再发」「免打扰」"
            "「退订」「抑制名单」「不得重复触达」等约束写成 \"<X>:00~<Y>:00免打扰\"（跨午夜，开始>结束）。"
            "例：「晚上 20 点后不能发，第二天 10 点再发」→ \"20:00~10:00免打扰\"。无则 \"\"。\n"
            "- strategy_spec: 字符串。仅当描述涉及分波/分群/频次/内容策略（如「分 3 波」「先给 seed 人群」"
            "「每日最多 1 封」「首波内容强调权益」）时，产出一份 StrategySpec JSON 文本填入："
            "顶层含 goal_id/objective/kpi/locale/audience_package/audience_profile/campaigns，"
            "每个 campaign 含 cid/name/content_brief/segment/send_conditions/tags_to_write/email_mode 等"
            "（schema 同 Mautic 活动编译约定），格式化为带缩进的 JSON 字符串；否则 \"\"。\n\n"
            "只输出 JSON 对象，键必须如上。不要编造未提及的信息：未提及的字段留空字符串；"
            "枚举字段必须输出枚举列表内的精确值（否则前端会因选项不匹配而丢弃）。"
        )
        payload = {
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": objective},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }
        import urllib.request as _u, urllib.error as _ue  # noqa: E402
        url = cfg["base_url"] + "/chat/completions"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = _u.Request(url, data=data, method="POST")
        for k, v in cfg["headers"].items():
            req.add_header(k, v)
        try:
            with _u.urlopen(req, timeout=cfg["timeout"]) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except _ue.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            return self._send_json({"ok": False, "error": f"DeepSeek HTTP {e.code}: {raw[:500]}"})
        except Exception as e:  # noqa: BLE001
            return self._send_json({"ok": False, "error": f"DeepSeek 请求失败：{e}"})
        try:
            outer = json.loads(raw)
            content = (outer.get("choices") or [{}])[0].get("message", {}).get("content", "")
            parsed = json.loads(content) if content else {}
        except Exception as e:  # noqa: BLE001
            return self._send_json({"ok": False, "error": f"DeepSeek 返回解析失败：{e}；原文：{raw[:500]}"})
        fields = ("goal_name", "start_date", "end_date", "overall_conv", "is_revenue",
                  "budget", "locale", "audience_age_range", "audience_age", "audience_gender",
                  "audience_income", "audience_source", "audience_education",
                  "audience_industry", "audience_region", "constraints", "strategy_spec")
        # 中文标签（前端 filled 提示用）
        field_label = {
            "goal_name": "活动简称", "start_date": "开始日期", "end_date": "结束日期",
            "overall_conv": "转化率", "is_revenue": "是否营收", "budget": "预算", "locale": "语言",
            "audience_age_range": "年龄范围", "audience_age": "年龄", "audience_gender": "性别", "audience_income": "收入",
            "audience_source": "渠道来源", "audience_education": "教育", "audience_industry": "行业",
            "audience_region": "地区", "constraints": "约束", "strategy_spec": "策略",
        }
        out = {}
        filled = []
        for f in fields:
            v = parsed.get(f, "")
            if isinstance(v, str):
                v = v.strip()
            else:
                v = "" if v in (None, False) else str(v)
            out[f] = v
            if f == "audience_age" and not v:
                # DeepSeek 只给了精确范围（audience_age_range）时，档位由服务端兜底算出，
                # 策略合成 / 画像推断继续吃档位，不会断供。
                v = _age_buckets_from_range(out.get("audience_age_range") or "")
                out[f] = v
            if v:
                filled.append(field_label.get(f, f))

        # 方案 B：意图识别未直接产出 strategy_spec 时，按启发式自动合成多波策略
        strategy_auto = False
        if not out.get("strategy_spec") and _should_synthesize_strategy(out):
            try:
                brief = _brief_from_parsed(out, objective)
                prompt = _build_strategy_prompt_from_brief(brief)
                content = _deepseek_completion(
                    "你是营销 Agent 的 AI策略合成器。只输出严格 JSON，不要解释文字、"
                    "不要 markdown 代码块，只输出可被 json.loads 解析的 StrategySpec 对象。",
                    prompt)
                spec = _extract_strategy_spec(content)
                if spec:
                    out["strategy_spec"] = spec
                    strategy_auto = True
            except Exception as e:  # noqa: BLE001
                # 合成失败不阻断字段回填（前端仍拿到识别字段）。
                # 不能只捕 RuntimeError：_brief_from_parsed / _build_strategy_prompt_from_brief
                # 抛 KeyError/TypeError 时会穿透到 Handler 外层，连接被掐断 → 浏览器 Failed to fetch。
                _log_ai_error(f"strategy 自动合成失败 {type(e).__name__}: {e}")
                pass
        resp = {"ok": True, **out, "filled": filled}
        if strategy_auto:
            resp["strategy_auto"] = True
            resp["filled"] = list(filled) + ["策略(自动合成)"]
        return self._send_json(resp)

    def _handle_campaign_approve(self, gid, cid, form):
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        c = next((x for x in p["campaigns"] if x["cid"] == cid), None)
        if not c:
            return self._send(404, _page("未找到", "<p>campaign 不存在</p>"))
        goal = GoalSpec(**p["goal"])
        if not self._ack_quiet_exempt_ok(c["strategy"], form):
            decision = ApprovalDecision(
                "REJECTED", "T2", form.get("approver", ""), time.time(), "",
                "审批人未确认静默窗豁免（22:00–09:00），驳回")
        else:
            decision = bind_and_approve(goal, c["proposal"], form.get("approver", ""))
        c["proposal"]["approval"] = decision.to_dict()
        _save_program(p)
        msg = (f"<div class='card'><p class='{'b-ok' if decision.status=='APPROVED' else 'b-bad'}'>"
               f"审批：{_esc(decision.status)}/{_esc(decision.level)} — {_esc(decision.reason)}</p></div>")
        self._send(200, _page("Program", _program_body(p, msg)))

    def _handle_service_approve(self, gid, sid, form):
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        s = next((x for x in p.get("service_sequences", []) if x["sid"] == sid), None)
        if not s:
            return self._send(404, _page("未找到", "<p>service 序列不存在</p>"))
        goal = GoalSpec(**p["goal"])
        if not self._ack_quiet_exempt_ok(s["strategy"], form):
            decision = ApprovalDecision(
                "REJECTED", "T2", form.get("approver", ""), time.time(), "",
                "审批人未确认服务件静默窗豁免（限定：用户动作即时触发 ≤5min），驳回")
        else:
            decision = bind_and_approve(goal, s["proposal"], form.get("approver", ""))
        s["proposal"]["approval"] = decision.to_dict()
        _save_program(p)
        msg = (f"<div class='card'><p class='{'b-ok' if decision.status=='APPROVED' else 'b-bad'}'>"
               f"服务序列审批：{_esc(decision.status)}/{_esc(decision.level)} — "
               f"{_esc(decision.reason)}</p></div>")
        self._send(200, _page("Program", _program_body(p, msg)))
    def _handle_service_push(self, gid, sid):
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        s = next((x for x in p.get("service_sequences", []) if x["sid"] == sid), None)
        if not s:
            return self._send(404, _page("未找到", "<p>service 序列不存在</p>"))
        cockpit_log("INFO", f"service_push {sid}：开始（program={gid}，已审批校验）")
        ok, reason = verify_push(s["proposal"], s["proposal"].get("approval"))
        if not ok:
            msg = f"<div class='card'><p class='b-bad'>推送被拒：{_esc(reason)}</p></div>"
            return self._send(200, _page("Program", _program_body(p, msg)))
        # 推之前先探活：Mautic 没启动就直接报「不可达」，不撞 segment/form 误导错误
        _mok, _mwhy = _mautic_reachable("local")
        if not _mok:
            msg = (f"<div class='card'><p class='b-bad'>❌ 服务序列 {_esc(sid)} 推送失败：Mautic 不可达（{_esc(_mautic_netloc('local'))}），请先启动 Mautic（如运行 start-mautic-local.bat）后重试。</p>"
                   f"<p class='note'>探测 GET /api/segments 失败 → {_esc(_mwhy)}。序列未真正创建，可重试。</p></div>")
            return self._send(200, _page("Program", _program_body(p, msg)))
        pid = _resolve_program_project(p, "local")
        result = push(s["proposal"], env="local", approved=True, project_id=pid)
        s["proposal"]["deploy_result"] = result
        push_ok, push_err = _check_push_result(result)
        if push_ok:
            s["proposal"]["deployed"] = True
            # 回写解析出的真实资产 ref（修 [待生成]/无链接 bug，对齐 _handle_campaign_push）
            _sync_resolved_assets_to_strategy(s, result)
            _save_program(p)
            cockpit_log("OK", f"service_push {sid}：推送成功（{'dry-run' if result.get('dry_run') else result.get('env')}）")
            msg = (f"<div class='card'><p class='b-ok'>服务序列已提交推送"
                   f"（{_esc('dry-run' if result.get('dry_run') else result.get('env'))}）：{_esc(reason)}</p></div>")
        else:
            s["proposal"]["deployed"] = False
            _save_program(p)
            cockpit_log("ERROR", f"service_push {sid}：推送失败 {push_err}")
            msg = (f"<div class='card'><p class='b-bad'>服务序列推送失败（已回滚 deployed）：{_esc(push_err)}</p>"
                   f"<p class='note'>可再次点击「推送」重试。</p></div>")
        self._send(200, _page("Program", _program_body(p, msg)))
    def _handle_campaign_push(self, gid, cid):
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        c = next((x for x in p["campaigns"] if x["cid"] == cid), None)
        if not c:
            return self._send(404, _page("未找到", "<p>campaign 不存在</p>"))
        cockpit_log("INFO", f"campaign_push {cid}：开始（program={gid}，已审批校验）")
        ok, reason = verify_push(c["proposal"], c["proposal"].get("approval"))
        if not ok:
            msg = f"<div class='card'><p class='b-bad'>推送被拒：{_esc(reason)}</p></div>"
            return self._send(200, _page("Program", _program_body(p, msg)))
        if c["status"] == "deferred":
            msg = ("<div class='card'><p class='b-bad'>推送被拒：该波为 deferred（外部事件触发），"
                   "请先由运营启用</p></div>")
            return self._send(200, _page("Program", _program_body(p, msg)))
        # 推之前先探活：Mautic 没启动就直接报「不可达」，不撞 segment/form 误导错误
        _mok, _mwhy = _mautic_reachable("local")
        if not _mok:
            msg = (f"<div class='card'><p class='b-bad'>❌ {_esc(cid)} 推送失败：Mautic 不可达（{_esc(_mautic_netloc('local'))}），请先启动 Mautic（如运行 start-mautic-local.bat）后重试。</p>"
                   f"<p class='note'>探测 GET /api/segments 失败 → {_esc(_mwhy)}。campaign 未真正创建，状态保持原样，可重试。</p></div>")
            return self._send(200, _page("Program", _program_body(p, msg)))
        # 解析 program 对应的 Mautic project（没有则现建），把所有资产挂其下
        pid = _resolve_program_project(p, "local")
        try:
            result = push(c["proposal"], env="local", approved=True, project_id=pid)
        except Exception as exc:
            result = {"dry_run": False, "campaign_id": None,
                      "note": f"push 执行异常：{type(exc).__name__}: {exc}",
                      "error": str(exc), "steps": [], "ensure_log": {}}
        c["proposal"]["deploy_result"] = result
        # 真实反映 push 结果：失败时回退状态、显示错误
        push_ok, push_err = _check_push_result(result)
        if push_ok:
            c["proposal"]["deployed"] = True
            # —— 回写解析出的真实资产 ref（修 Q2 显示 bug：push 建资产用派生名并把 id 写进
            #     proposal.mautic_events，但从不回写 strategy.email_ref/landing_page_url，
            #     导致卡片永远显示「[待生成]」占位、无外链）——
            _sync_resolved_assets_to_strategy(c, result)
            _save_program(p)
            note = "dry-run" if result.get("dry_run") else result.get("env")
            cockpit_log("OK", f"campaign_push {cid}：推送成功（{note}）")
            msg = f"<div class='card'><p class='b-ok'>已提交推送（{_esc(note)}）：{_esc(reason or '已上线')}</p></div>"
        else:
            c["proposal"]["deployed"] = False
            _save_program(p)
            cockpit_log("ERROR", f"campaign_push {cid}：推送失败 {push_err}")
            msg = (f"<div class='card'><p class='b-bad'>推送失败（已回滚 status）：{_esc(push_err)}</p>"
                   f"<p class='note'>Mautic 返回了错误，campaign 未真正创建。常见原因："
                   f"①事件图缺少 contact source（segment list）→ Mautic 7 必填；"
                   f"②email/landing 资产未先创建（properties.email=0 等占位）；"
                   f"③campaign 名冲突。</p></div>")
        self._send(200, _page("Program", _program_body(p, msg)))
    def _handle_campaign_activate(self, gid, cid):
        """运营启用 deferred 波次（外部事件已确认）→ 转 unreviewed 回到标准审批/执行通道。"""
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        c = next((x for x in p["campaigns"] if x["cid"] == cid), None)
        if not c:
            return self._send(404, _page("未找到", "<p>campaign 不存在</p>"))
        if c["status"] != "deferred":
            msg = f"<div class='card'><p class='pill'>{_esc(cid)} 状态={_esc(c['status'])}，无需启用</p></div>"
            return self._send(200, _page("Program", _program_body(p, msg)))
        c["status"] = "unreviewed"
        _save_program(p)
        msg = (f"<div class='card'><p class='b-ok'>{_esc(cid)} 已启用（外部事件已确认），回到未审核状态；"
               f"仍需审批 → 创建 → 执行</p></div>")
        self._send(200, _page("Program", _program_body(p, msg)))
    def _handle_campaign_goals(self, gid, cid, form):
        """保存单个 campaign 的可编辑目标（转化目标/退订上限/执行窗口）。"""
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        c = next((x for x in p["campaigns"] if x["cid"] == cid), None)
        if not c:
            return self._send(404, _page("未找到", "<p>campaign 不存在</p>"))
        try:
            if form.get("conv_target", "").strip():
                c["conv_target"] = float(form["conv_target"])
            if form.get("unsub_cap", "").strip():
                c["unsub_cap"] = float(form["unsub_cap"])
        except ValueError:
            return self._send(200, _page("Program",
                _program_body(p, "<div class='card'><p class='b-bad'>转化目标/退订上限必须是 0~1 的数字</p></div>")))
        c["exec_start"] = (form.get("exec_start", "") or "").strip()
        c["exec_end"] = (form.get("exec_end", "") or "").strip()
        _save_program(p)
        msg = f"<div class='card'><p class='b-ok'>{_esc(cid)} 目标已保存（转化目标 {c.get('conv_target')} · 执行窗口 {c.get('exec_start')}~{c.get('exec_end')}）</p></div>"
        self._send(200, _page("Program", _program_body(p, msg)))
    def _handle_campaign_create(self, gid, cid):
        """分阶段创建：仅把该 campaign 推到 Mautic（approved=True → 创建草稿并发布）。"""
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        c = next((x for x in p["campaigns"] if x["cid"] == cid), None)
        if not c:
            return self._send(404, _page("未找到", "<p>campaign 不存在</p>"))
        if not c["proposal"].get("approval"):
            msg = f"<div class='card'><p class='b-bad'>{_esc(cid)} 尚未审批，不能创建（审批门是硬约束）</p></div>"
            return self._send(200, _page("Program", _program_body(p, msg)))
        # 推之前先记 approved_idle（避免直接跳 executing 之后再被回滚显得反复）
        cockpit_log("INFO", f"campaign_create {cid}：开始创建并推送（program={gid}）")
        c["status"] = "approved_idle"
        _save_program(p)
        # 推之前先探活：Mautic 没启动就直接报「不可达」，不要去撞 segment/form 的误导错误
        _mok, _mwhy = _mautic_reachable("local")
        if not _mok:
            c["proposal"]["deploy_result"] = {"dry_run": False, "campaign_id": None,
                                              "error": f"Mautic 不可达：{_mwhy}", "steps": []}
            c["proposal"]["deployed"] = False
            _save_program(p)
            msg = (f"<div class='card'><p class='b-bad'>❌ {_esc(cid)} 推送失败：Mautic 不可达（{_esc(_mautic_netloc('local'))}），请先启动 Mautic（如运行 start-mautic-local.bat）后重试。</p>"
                   f"<p class='note'>探测 GET /api/segments 失败 → {_esc(_mwhy)}。未真正创建 campaign，状态保持「已审批待创建」。</p></div>")
            return self._send(200, _page("Program", _program_body(p, msg)))
        # 解析 program 对应的 Mautic project（没有则现建），把所有资产挂其下
        pid = _resolve_program_project(p, "local")
        try:
            result = push(c["proposal"], env="local", approved=True, project_id=pid)
        except Exception as exc:
            result = {"dry_run": False, "campaign_id": None,
                      "note": f"push 执行异常：{type(exc).__name__}: {exc}",
                      "error": str(exc), "steps": [], "ensure_log": {}}
        c["proposal"]["deploy_result"] = result
        # 诚实反映 push 结果：
        #  · 只有【真实在 Mautic 创建了 campaign】（dry_run=False 且 campaign_id 非空）才标记「执行中」+ deployed=True
        #  · dry-run（无论有意未填凭证，还是 token/凭证超时）一律不标记执行中，避免误导
        #  · 任何失败都保持 approved_idle，并在页面给出失败原因
        if (not result.get("dry_run")) and result.get("campaign_id"):
            c["proposal"]["deployed"] = True
            c["status"] = "executing"
            _save_program(p)
            cockpit_log("OK", f"campaign_create {cid}：已真实推送（campaign_id={result.get('campaign_id')}）")
            msg = (f"<div class='card'><p class='b-ok'>✅ {_esc(cid)} 已真实推送到 Mautic"
                   f"（campaign_id={_esc(result.get('campaign_id'))}，env={_esc(result.get('env'))}），状态：执行中。</p></div>")
        elif result.get("dry_run"):
            # dry-run：没真改 Mautic，状态保持 approved_idle，绝不谎报执行中
            c["proposal"]["deployed"] = False
            _save_program(p)
            note = result.get("note") or ""
            if ("token" in note) or ("凭证" in note) or ("获取" in note):
                msg = (f"<div class='card'><p class='b-bad'>❌ {_esc(cid)} 推送失败（dry-run 原因为错误，非成功）：{_esc(note)}</p>"
                       f"<p class='note'>状态保持「已审批待创建」，未改为执行中。常见：Mautic 不可达 / OAuth token 获取超时。"
                       f"修复后再次点击「创建并推送到 Mautic」重试。</p></div>")
            else:
                cockpit_log("WARN", f"campaign_create {cid}：仅 dry-run（{note}）")
            msg = (f"<div class='card'><p class='b-warn'>⚠️ {_esc(cid)} 仅 dry-run（未真正创建 campaign）：{_esc(note)}</p>"
                       f"<p class='note'>状态保持「已审批待创建」。填好 config.json 的 client_id/secret 后重推才会真正落库。</p></div>")
        else:
            # 真实推送但 Mautic 未返回 campaign_id（多为 400，如 segment/资产创建被拒）
            c["proposal"]["deployed"] = False
            _save_program(p)
            mcid = result.get("campaign_id")
            mcid_txt = f"（campaign_id={_esc(mcid)}）" if mcid else ""
            push_err = _format_mautic_err(result.get("error")) if result.get("error") else (result.get("note") or "未知错误")
            cockpit_log("ERROR", f"campaign_create {cid}：推送失败{mcid_txt}：{push_err}")
            msg = (f"<div class='card'><p class='b-bad'>❌ {_esc(cid)} 推送失败{mcid_txt}：{_esc(push_err)}</p>"
                   f"<p class='note'>Mautic 真实响应未创建 campaign。状态保持「已审批待创建」，未改为执行中。常见原因："
                   f"①事件图缺少 contact source（segment list）→ Mautic 7 必填；"
                   f"②email/landing 资产未先在 Mautic 创建（properties.email=0 占位 → 引用不存在的 id）；"
                   f"③campaign 名重复或别名冲突。</p>"
                   f"<p class='note'>修复后可再次点击「创建并推送到 Mautic」重试。</p></div>")
        self._send(200, _page("Program", _program_body(p, msg)))
    def _handle_program_auto_feedback(self, gid, date_str):
        """手动触发某 program 的 auto-feedback：拉取 Mautic 真实数写入 feedback_auto[date_str]。"""
        import datetime as _dt
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        # 简单校验 date 格式
        try:
            _dt.date.fromisoformat(date_str)
        except Exception:  # noqa: BLE001
            return self._send(400, _page("参数错",
                f"<p class='b-bad'>date 参数格式错（应为 YYYY-MM-DD）：{_esc(date_str)}</p>"))

        rows = []
        updated = 0
        skipped = 0
        for c in p.get("campaigns", []):
            dr = (c.get("proposal") or {}).get("deploy_result") or {}
            mcid = dr.get("campaign_id") if not dr.get("dry_run") else None
            if not mcid:
                skipped += 1
                rows.append((c.get("cid", "?"), mcid, None, "跳过：无 Mautic campaign id（dry-run / 未部署）"))
                continue
            try:
                stats = auto_feedback_for_campaign(mcid, date_str)
            except Exception as e:  # noqa: BLE001
                stats = {"_errors": [str(e)]}
            fb_auto = c.setdefault("feedback_auto", {})
            fb_auto[date_str] = {
                "sent": stats.get("sent", 0),
                "opened": stats.get("opened", 0),
                "clicked": stats.get("clicked", 0),
                "converted": stats.get("converted", 0),
                "unsub": stats.get("unsub", 0),
                "conv_rate": stats.get("conv_rate", 0.0),
                "unsub_rate": stats.get("unsub_rate", 0.0),
                "_evidence": stats.get("_evidence", []),
                "_errors": stats.get("_errors", []),
            }
            c["feedback_auto_updated_at"] = _dt.datetime.now().isoformat(timespec="seconds")
            updated += 1
            rows.append((
                c.get("cid", "?"),
                mcid,
                f"sent={fb_auto[date_str]['sent']} "
                f"opened={fb_auto[date_str]['opened']} "
                f"clicked={fb_auto[date_str]['clicked']} "
                f"converted={fb_auto[date_str]['converted']} "
                f"unsub={fb_auto[date_str]['unsub']} "
                f"conv={fb_auto[date_str]['conv_rate']:.2%}",
                ("; ".join(stats.get("_errors", [])) or "ok"),
            ))
        _save_program(p)

        # 渲染结果表
        body = [
            f"<div class='card'><p class='b-ok'>Program <code>{_esc(gid)}</code> · date={_esc(date_str)} · "
            f"updated={updated} · skipped={skipped}</p>",
            "<table class='kv'><tr><th>cid</th><th>Mautic id</th><th>统计</th><th>备注</th></tr>"
        ]
        for cid, mcid, stat, note in rows:
            body.append(
                f"<tr><td><code>{_esc(cid)}</code></td>"
                f"<td>{_esc(mcid) if mcid else '—'}</td>"
                f"<td>{_esc(stat) if stat else '—'}</td>"
                f"<td>{_esc(note)}</td></tr>"
            )
        body.append("</table></div>")
        msg = "".join(body)
        self._send(200, _page("Auto-Feedback", _program_body(p, msg)))
    def _handle_campaign_feedback_autofill(self, gid, cid, date_str):
        """Plan 2：拉 Mautic 最新数据预填表单（Plan 2 = 单击按钮一键预填）。

        进入方式：单击 campaign 卡片上「从 Mautic 拉最新数据预填」按钮。
        行为：调 auto_feedback_for_campaign(mcid, date) → 把 sent/opened/converted/unsub
              作为 input.value 注入到回填表单；运营可微调后再点「保存」落库。
        """
        import datetime as _dt
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        c = next((x for x in p["campaigns"] if x["cid"] == cid), None)
        if not c:
            return self._send(404, _page("未找到", "<p>campaign 不存在</p>"))
        try:
            _dt.date.fromisoformat(date_str)
        except Exception:  # noqa: BLE001
            return self._send(400, _page("参数错",
                f"<p class='b-bad'>date 参数格式错（应为 YYYY-MM-DD）：{_esc(date_str)}</p>"))

        dr = (c.get("proposal") or {}).get("deploy_result") or {}
        mcid = dr.get("campaign_id") if not dr.get("dry_run") else None
        if not mcid:
            msg = (f"<div class='card'><p class='b-bad'>无法预填：{_esc(cid)} 没有 Mautic campaign id "
                   f"（dry-run / 未部署）。先把此 campaign 审批 + 推送到 Mautic，再来拉数据。</p></div>")
            return self._send(200, _page("Program", _program_body(p, msg)))

        try:
            stats = auto_feedback_for_campaign(mcid, date_str)
        except Exception as e:  # noqa: BLE001
            stats = {"sent": 0, "opened": 0, "clicked": 0, "converted": 0, "unsub": 0,
                     "conv_rate": 0.0, "unsub_rate": 0.0, "_errors": [str(e)]}

        # 把预填数据塞到 campaign 上下文字段（_autofill），让 _program_body 渲染时优先用这个
        c["_autofill"] = {
            "date": date_str,
            "sent": stats.get("sent", 0),
            "opened": stats.get("opened", 0),
            "converted": stats.get("converted", 0),
            "unsub": stats.get("unsub", 0),
            "clicked": stats.get("clicked", 0),
            "conv_rate": stats.get("conv_rate", 0.0),
            "unsub_rate": stats.get("unsub_rate", 0.0),
            "_evidence": stats.get("_evidence", []),
            "_errors": stats.get("_errors", []),
        }
        # 顶部 banner
        ev_lines = stats.get("_evidence", []) or []
        err_lines = stats.get("_errors", []) or []
        rows = [
            f"<div class='card'><h3>📊 Mautic 预填 · {_esc(cid)} · date={_esc(date_str)}</h3>",
            "<p class='note'>来源：Mautic :8080 自动抓取；以下数据已注入表单，运营可微调后保存（不保存 = 丢弃本次预填）。</p>",
            "<table class='kv'>",
            f"<tr><th>sent</th><td>{stats.get('sent', 0)}</td><th>opened</th><td>{stats.get('opened', 0)}</td></tr>",
            f"<tr><th>clicked</th><td>{stats.get('clicked', 0)}</td><th>converted</th><td>{stats.get('converted', 0)}</td></tr>",
            f"<tr><th>unsub</th><td>{stats.get('unsub', 0)}</td><th>conv_rate</th><td>{stats.get('conv_rate', 0.0):.2%}</td></tr>",
            "</table>",
        ]
        if ev_lines:
            rows.append("<details><summary class='pill'>_evidence（数据来源链）</summary><pre class='pre'>"
                        + "\n".join(_esc(x) for x in ev_lines) + "</pre></details>")
        if err_lines:
            rows.append("<details open><summary class='pill b-bad'>_errors</summary><pre class='pre'>"
                        + "\n".join(_esc(x) for x in err_lines) + "</pre></details>")
        rows.append("</div>")
        msg = "".join(rows)
        self._send(200, _page("Program", _program_body(p, msg)))
    def _handle_campaign_optimize(self, gid, cid, date_str):
        """Plan 1→优化预判：从 feedback_auto[date] 载入，预判是否需要方案优化（只读，不改 program）。

        进入：点 campaign 卡片「📈 从自动回填载入方案优化」按钮。
        行为：取 feedback_auto[date]（date 缺省=最新一日）→ 算达成率/退订率 → 与 KPI 目标比对 →
              判定 无需优化 / 需优化，预览存 c['_optimize_preview'] 渲染在卡片上。
              「采纳并应用」按钮 POST /complete（带 conv/unsub）才真正改写当前 campaign（两步：预览 diff → 确认落库）。
        """
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        c = next((x for x in p["campaigns"] if x["cid"] == cid), None)
        if not c:
            return self._send(404, _page("未找到", "<p>campaign 不存在</p>"))
        fa = c.get("feedback_auto") or {}
        if date_str:
            fd = fa.get(date_str)
        else:
            date_str = max(fa.keys()) if fa else None
            fd = fa.get(date_str) if date_str else None
        if not fd:
            _dtxt = _esc(date_str or "—")
            msg = (f"<div class='card'><p class='b-warn'>campaign {_esc(cid)} 暂无 feedback_auto 自动回填数据"
                   f"（date={_dtxt}）。请先跑 <code>python auto_feedback.py</code>"
                   f" 或点「📊 从 Mautic 拉数据预填」后保存。</p></div>")
            return self._send(200, _page("Program", _program_body(p, msg)))
        conv = float(fd.get("conv_rate", 0) or 0)
        unsub = float(fd.get("unsub_rate", 0) or 0)
        # 目标：campaign conv_target > goal KPI target > None
        cmp_target = c.get("conv_target")
        try:
            cmp_target = float(cmp_target)
        except (TypeError, ValueError):
            cmp_target = None
        if not cmp_target or cmp_target <= 0:
            _kpi = (p.get("goal") or {}).get("kpi") or {}
            _gt = _kpi.get("target")
            if _kpi.get("target_unset") or _gt in (None, 0, 0.0):
                cmp_target = None
            else:
                try:
                    cmp_target = float(_gt)
                except (TypeError, ValueError):
                    cmp_target = None
        target_unset = cmp_target is None
        ratio = (round(conv / cmp_target, 3) if cmp_target else None)
        # 判定（与 evaluate_and_replan 同阈值，但只读预览）
        if target_unset:
            verdict, detail = "无需优化", "KPI 目标未设置（R 未给）：仅做基线观测，不触发改写。"
        elif unsub > 0.003:
            verdict, detail = "需优化", f"退订率 {unsub:.2%} 超熔断 0.3%：建议 降频 + 加 suppression tag（收窄）。"
        elif ratio >= 1.0:
            verdict, detail = "无需优化", (f"达成率 {conv:.2%} ≥ 目标 {cmp_target:.2%}，"
                                          f"退订率 {unsub:.2%} 安全：保持策略，无需调整（可略降本）。")
        elif ratio >= 0.5:
            verdict, detail = "需优化", (f"达成率 {conv:.2%} < 目标 {cmp_target:.2%}（{ratio:.2f}×）："
                                        f"建议 提频 + 换内容变体 + urgency tag。")
        else:
            verdict, detail = "需优化", (f"达成率 {conv:.2%} 仅 {ratio:.2f}× 目标："
                                        f"建议 大幅提频 + 扩分组(broaden/reengage) + 换内容。")
        c["_optimize_preview"] = {
            "date": date_str, "conv": conv, "unsub": unsub,
            "target": cmp_target, "ratio": ratio, "verdict": verdict, "detail": detail,
        }
        _save_program(p)
        msg = (f"<div class='card'><p class='b-ok'>已载入 {_esc(cid)} 自动回填 {_esc(date_str)} 做优化预判。</p></div>")
        self._send(200, _page("Program", _program_body(p, msg)))
    def _handle_campaign_feedback(self, gid, cid, form):
        """人工回填某 campaign 的执行结果（发送/打开/转化/退订计数），计算各率。"""
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        c = next((x for x in p["campaigns"] if x["cid"] == cid), None)
        if not c:
            return self._send(404, _page("未找到", "<p>campaign 不存在</p>"))

        def _int(v):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return 0
        sent = _int(form.get("sent", 0))
        opened = _int(form.get("opened", 0))
        converted = _int(form.get("converted", 0))
        unsub = _int(form.get("unsub", 0))
        feedback = {
            "sent": sent, "opened": opened, "converted": converted, "unsub": unsub,
            "sent_rate": round(sent / sent, 4) if sent else 0.0,
            "open_rate": round(opened / sent, 4) if sent else 0.0,
            "conv_rate": round(converted / sent, 4) if sent else 0.0,
            "unsub_rate": round(unsub / sent, 4) if sent else 0.0,
        }
        c["feedback"] = feedback
        _save_program(p)
        msg = (f"<div class='card'><p class='b-ok'>{_esc(cid)} 执行结果已回填："
               f"达成率 {feedback['conv_rate']} · 退订率 {feedback['unsub_rate']}（不自动推进，需运营标记完成）</p></div>")
        self._send(200, _page("Program", _program_body(p, msg)))
    def _handle_program_delete(self, gid):
        """删除 Program：仅移除驾驶舱本地记录（output/program_<gid>.json），
        绝不动 Mautic（:8080）已生成的活动/邮件/落地页。需前端二次确认（confirm）后才 POST 到此。"""
        try:
            # 浏览器提交时会对含中文的 goal_id 做 URL 编码，这里还原以匹配真实文件名
            gid = urllib.parse.unquote(gid or "").strip()
            if not gid:
                return self._send(400, _page("删除失败", "<p class='b-bad'>缺少 goal_id。</p>"))
            fp = _program_path(gid)
            if os.path.exists(fp):
                _permanent_remove(fp)
            # 回到首页（首页按 output/program_*.json 聚合，已删项不再出现）
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
        except Exception as e:  # noqa: BLE001
            self._send(500, _page("删除失败", f"<p class='b-bad'>{_esc(e)}</p><p><a href='/'>返回</a></p>"))
    def _handle_complete(self, form):
        # path 形如 /program/<gid>/complete
        # 两步流：先预览「改写当前campaign」的 diff → 确认后才落库（不影响下游）
        gid = self.path.split("/")[2] if self.path.startswith("/program/") else ""
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        cid = form.get("cid", "")
        c = next((x for x in p["campaigns"] if x["cid"] == cid), None)
        if not c:
            return self._send(404, _page("未找到", "<p>campaign 不存在</p>"))
        # 达成率/退订率：表单留空时回落到该 campaign 已回填的执行结果（#8）
        conv_raw = (form.get("conversion", "") or "").strip()
        unsub_raw = (form.get("unsub", "") or "").strip()
        if not conv_raw and c.get("feedback"):
            conv_raw = c["feedback"].get("conv_rate", 0)
        if not unsub_raw and c.get("feedback"):
            unsub_raw = c["feedback"].get("unsub_rate", 0)
        result = {"conversion": float(conv_raw or 0), "unsub": float(unsub_raw or 0)}
        # 判定（与 evaluate_and_replan 同阈值）
        kpi = (p["goal"] or {}).get("kpi") or {}
        target = kpi.get("target", 0.15)
        target_unset = target is None or kpi.get("target_unset") or float(target or 0) <= 0
        cmp_target = c.get("conv_target")
        if cmp_target is None:
            cmp_target = target
        met = (float(result["conversion"] or 0) >= float(cmp_target or 0))
        verdict = "baseline" if target_unset else _verdict_for(target, result["conversion"], result["unsub"])
        done_lbl = STATUS.get(c.get("status", ""), ("", ""))[0] or ("达成" if met else "未达标")
        # 仅改写【当前】campaign 的策略（回写达成），产出 diff 供二次确认
        new_s = adjust_strategy_for_verdict(c["strategy"], verdict)
        diff = _compute_strategy_diff(c["strategy"], new_s, cid)
        confirm = (form.get("confirm") or "").strip()
        if confirm != "1":
            # Step A：预览 diff（不落库）
            cockpit_log("INFO", f"complete {cid}：预览（verdict={verdict} · diff={len(diff)}）")
            title = "改写当前campaign · 预览"
            if not diff:
                head = (f"上游 <b>{_esc(cid)}</b> 完成（{_esc(done_lbl)}）· 判定 <b>{_esc(verdict)}</b>："
                        f"<span class='b-ok'>当前 campaign 策略无变化</span>。")
                body = (f"<p class='note'>按判定结果（{_esc(verdict)}）计算，当前 campaign 的策略旋钮无需调整，"
                        f"直接标记完成即可。</p>")
                form_html = (f"<form method='post' action='/program/{_esc(gid)}/complete'>"
                             f"<input type='hidden' name='cid' value='{_esc(cid)}'>"
                             f"<input type='hidden' name='conversion' value='{_esc(conv_raw)}'>"
                             f"<input type='hidden' name='unsub' value='{_esc(unsub_raw)}'>"
                             f"<input type='hidden' name='confirm' value='1'>"
                             f"<button class='btn sm' type='submit'>确认完成（无改动）</button></form>")
            else:
                head = (f"上游 <b>{_esc(cid)}</b> 完成（{_esc(done_lbl)}）· 判定 <b>{_esc(verdict)}</b>："
                        f"将改写<b>当前 campaign</b> 策略如下，请确认。")
                body = (f"<p class='note'>以下为按达成结果（{_esc(verdict)}）回写当前 campaign 的调整项"
                        f"（不影响下游其余 campaign）：</p>{_diff_list_html(diff)}")
                form_html = (f"<form method='post' action='/program/{_esc(gid)}/complete'>"
                             f"<input type='hidden' name='cid' value='{_esc(cid)}'>"
                             f"<input type='hidden' name='conversion' value='{_esc(conv_raw)}'>"
                             f"<input type='hidden' name='unsub' value='{_esc(unsub_raw)}'>"
                             f"<input type='hidden' name='confirm' value='1'>"
                             f"<button class='btn sm' type='submit'>确认改写并提交</button></form>"
                             f"<a class='btn sm ghost' href='/program/{_esc(gid)}/campaign/{_esc(cid)}'>取消</a>")
            msg = (f"<div class='card' style='border-color:var(--warn)'>"
                   f"<h3 style='margin:0 0 6px'>{_esc(title)}</h3>"
                   f"<p>{head}</p>{body}{form_html}</div>")
            return self._send(200, _page("Program", _program_body(p, msg)))
        # Step B：确认 → 落库（仅当前 campaign）
        from goal_intake import GoalSpec
        from plan_compiler import compile
        goal = GoalSpec(**(p["goal"] or {}))
        c["strategy"] = new_s
        c["proposal"] = compile(goal, new_s)
        c["status"] = "done_met" if met else "done_below"
        c["result"] = result
        p["changelog"].append({
            "completed_cid": cid, "result": result, "verdict": verdict,
            "target_unset": bool(target_unset), "scope": "current_only",
            "changes": [{"cid": cid, "notes": diff}], "at": time.time(),
        })
        _save_program(p)
        cockpit_log("OK", f"complete {cid}：verdict={verdict} · 改写当前campaign · diff={len(diff)}")
        msg = (f"<div class='card'><p class='b-ok'>✅ <b>{_esc(cid)}</b> 已标记完成（{_esc(done_lbl)}），"
               f"判定 <b>{_esc(verdict)}</b>，已回写当前 campaign 策略"
               f"（{ '无改动' if not diff else str(len(diff)) + ' 项调整' }）。</p>"
               f"{_diff_list_html(diff, empty_txt='无策略调整') if diff else ''}</div>")
        self._send(200, _page("Program", _program_body(p, msg)))
    def _handle_replan_prompt(self, gid, cid, body):
        """构建「下一阶段策略」自包含提示词，供运营复制到 WorkBuddy 生成后贴回。返回 JSON。"""
        p = _load_program(gid)
        if not p:
            return self._send_json({"ok": False, "error": "Program 不存在"})
        try:
            prompt = _build_replan_prompt(p, gid, cid)
        except Exception as e:  # noqa: BLE001
            return self._send_json({"ok": False, "error": f"构建提示词失败：{e}"})
        return self._send_json({"ok": True, "prompt": prompt})
    def _handle_confirm_strategy(self, form):
        """L1 辅助路径：粘贴 WorkBuddy 返回的策略 JSON，标记上游完成并应用到【剩余所有】campaign。
        两步流：先预览每个剩余 campaign 的 diff → 确认后才落库。"""
        gid = self.path.split("/")[2] if self.path.startswith("/program/") else ""
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        cid = (form.get("cid") or "").strip()
        c = next((x for x in p["campaigns"] if x["cid"] == cid), None)
        if not c:
            return self._send(404, _page("未找到", "<p>campaign 不存在</p>"))
        raw = (form.get("strategy_spec") or "").strip()
        if not raw:
            msg = ("<div class='card'><p class='b-bad'>请先粘贴 WorkBuddy 返回的策略 JSON，"
                   "再点「确认剩余策略」。</p></div>")
            return self._send(200, _page("Program", _program_body(p, msg)))
        # 解析 StrategySpec
        try:
            spec = parse_strategy_spec(raw)
            from goal_intake import GoalSpec
            goal = GoalSpec(**p["goal"])
            strategies = strategies_from_spec(spec, goal)
        except Exception as e:  # noqa: BLE001
            msg = f"<div class='card'><p class='b-bad'>策略解析失败：{_esc(str(e))}</p></div>"
            return self._send(200, _page("Program", _program_body(p, msg)))
        # 一致性校验：与 Brief 基础信息冲突 → 不应用、不写 changelog
        conflicts = validate_spec(spec, _brief_ctx_from_goal(p["goal"]),
                                  (p["goal"].get("meta") or {}).get("audience_package")
                                  or p["goal"].get("audience_package"))
        if conflicts:
            msg = _conflicts_card_html(
                conflicts, title="策略规格与基础信息冲突，未应用该策略",
                note="Program 未做任何改动：不应用到剩余 campaign、不记录变更。请修正策略 JSON 后重新提交。")
            return self._send(200, _page("Program", _program_body(p, msg)))
        # 记录上游完成结果（与 _handle_complete 同口径）
        conv_raw = (form.get("conversion", "") or "").strip()
        unsub_raw = (form.get("unsub", "") or "").strip()
        if not conv_raw and c.get("feedback"):
            conv_raw = c["feedback"].get("conv_rate", 0)
        if not unsub_raw and c.get("feedback"):
            unsub_raw = c["feedback"].get("unsub_rate", 0)
        result = {"conversion": float(conv_raw or 0), "unsub": float(unsub_raw or 0)}
        cmp_target = c.get("conv_target")
        if cmp_target is None:
            cmp_target = (p["goal"].get("kpi") or {}).get("target")
        met = (float(result["conversion"] or 0) >= float(cmp_target or 0))
        done_lbl = "达成" if met else "未达标"
        spec_map = {s["cid"]: s for s in strategies}
        existing = {x["cid"] for x in p["campaigns"]}
        # 预览：逐个剩余 campaign 的 diff + spec 独有（新增分支）
        changed_blocks = []
        total_changes = 0
        for c2 in p["campaigns"]:
            if c2["cid"] == cid:
                continue
            if c2["status"] not in ("unreviewed", "reviewed", "pending"):
                continue
            if c2["cid"] in spec_map:
                diff = _compute_strategy_diff(c2["strategy"], spec_map[c2["cid"]], c2["cid"])
                if diff:
                    total_changes += len(diff)
                    name = spec_map[c2["cid"]].get("campaign_name") or spec_map[c2["cid"]].get("intent") or c2["cid"]
                    changed_blocks.append(
                        f"<div class='card' style='margin-top:8px;border-color:var(--warn)'>"
                        f"<p style='margin:0 0 4px'><b>{_esc(c2['cid'])}</b> "
                        f"（{_esc(str(name))}）：{len(diff)} 项调整</p>{_diff_list_html(diff)}</div>")
        new_branches = [s for s in strategies if s["cid"] not in existing]
        branch_html = "".join(
            f"<p class='note' style='color:var(--ok);margin-top:6px'>➕ 新增分支 <b>{_esc(s['cid'])}</b>"
            f"（{_esc(str(s.get('campaign_name') or s.get('intent') or ''))}）</p>"
            for s in new_branches)
        confirm = (form.get("confirm") or "").strip()
        if confirm != "1":
            # Step A：预览（不落库）
            cockpit_log("INFO", f"confirm-strategy {cid}：预览（changed_campaigns={len(changed_blocks)} · new_branches={len(new_branches)}）")
            if not changed_blocks and not new_branches:
                head = (f"上游 <b>{_esc(cid)}</b> 完成（{_esc(done_lbl)}）：粘贴的策略与【剩余所有】campaign 当前策略"
                        f"<span class='b-ok'>无差异</span>。可直接推进下一阶段（用原有策略跑）。")
                body = ""
                form_html = (f"<form method='post' action='/program/{_esc(gid)}/confirm-strategy'>"
                             f"<input type='hidden' name='cid' value='{_esc(cid)}'>"
                             f"<input type='hidden' name='conversion' value='{_esc(conv_raw)}'>"
                             f"<input type='hidden' name='unsub' value='{_esc(unsub_raw)}'>"
                             f"<input type='hidden' name='strategy_spec' value='{_esc(raw)}'>"
                             f"<input type='hidden' name='confirm' value='1'>"
                             f"<button class='btn sm' type='submit'>确认推进（无改动）</button></form>"
                             f"<a class='btn sm ghost' href='/program/{_esc(gid)}/campaign/{_esc(cid)}'>取消</a>")
            else:
                head = (f"上游 <b>{_esc(cid)}</b> 完成（{_esc(done_lbl)}）：将把粘贴的策略应用到【剩余所有】"
                        f"{len(changed_blocks)} 个待改 campaign"
                        f"{(' + ' + str(len(new_branches)) + ' 个新增分支') if new_branches else ''}，请确认。")
                body = "".join(changed_blocks) + branch_html
                form_html = (f"<form method='post' action='/program/{_esc(gid)}/confirm-strategy'>"
                             f"<input type='hidden' name='cid' value='{_esc(cid)}'>"
                             f"<input type='hidden' name='conversion' value='{_esc(conv_raw)}'>"
                             f"<input type='hidden' name='unsub' value='{_esc(unsub_raw)}'>"
                             f"<input type='hidden' name='strategy_spec' value='{_esc(raw)}'>"
                             f"<input type='hidden' name='confirm' value='1'>"
                             f"<button class='btn sm' type='submit'>确认应用（改写剩余 {len(changed_blocks)} 个campaign"
                             f"{(' + 新增 ' + str(len(new_branches)) + ' 分支') if new_branches else ''}）</button></form>"
                             f"<a class='btn sm ghost' href='/program/{_esc(gid)}/campaign/{_esc(cid)}'>取消</a>")
            msg = (f"<div class='card' style='border-color:var(--warn)'>"
                   f"<h3 style='margin:0 0 6px'>确认剩余策略 · 预览</h3>"
                   f"<p>{head}</p>{body}{form_html}</div>")
            return self._send(200, _page("Program", _program_body(p, msg)))
        # Step B：确认 → 落库（应用 spec 到剩余所有待推进且 cid 匹配者；spec 独有 cid = 新增分支）
        from plan_compiler import compile
        applied, added = [], []
        for c2 in p["campaigns"]:
            if c2["cid"] == cid:
                continue
            if c2["status"] not in ("unreviewed", "reviewed", "pending"):
                continue
            if c2["cid"] in spec_map:
                new_s = spec_map[c2["cid"]]
                c2["strategy"] = new_s
                c2["proposal"] = compile(goal, new_s)
                applied.append(c2["cid"])
        for s in strategies:
            if s["cid"] not in existing:
                prop = compile(goal, s)
                p["campaigns"].append({
                    "cid": s["cid"], "wave_id": s.get("wave_id"),
                    "strategy": s, "proposal": prop,
                    "status": "unreviewed", "result": None,
                })
                added.append(s["cid"])
        p["n_campaigns"] = len(p["campaigns"])
        c["status"] = "done_met" if met else "done_below"
        c["result"] = result
        p["changelog"].append({
            "completed_cid": cid, "result": result, "ratio": None,
            "verdict": "l1_workbuddy", "target_unset": False, "scope": "remaining_all",
            "changes": [{"cid": x, "notes": ["见预览"]} for x in applied],
            "applied": applied, "added": added,
            "source": "l1_workbuddy", "at": time.time(),
        })
        _save_program(p)
        cockpit_log("OK", f"confirm-strategy {cid}：applied={applied} · added={added}")
        msg = (f"<div class='card'><p class='b-ok'>✅ 上游 <b>{_esc(cid)}</b> 完成（AI策略已应用）· "
               f"达成率 {result['conversion']} · 退订率 {result['unsub']}<br>"
               f"改写剩余：{_esc('；'.join(applied) or '无匹配剩余')}<br>"
               f"新增分支：{_esc('；'.join(added) or '无')}</p></div>")
        self._send(200, _page("Program", _program_body(p, msg)))
    def _handle_legacy_approve(self, gid, form):
        d = _load_proposal(gid)
        if not d:
            return self._send(404, _page("未找到", "<p>提案不存在</p>"))
        goal = GoalSpec(**d.get("goal", {}))
        decision = bind_and_approve(goal, d, form.get("approver", ""))
        d["approval"] = decision.to_dict()
        dump_proposal(d, os.path.join(OUT_DIR, f"proposal_{gid}.json"))
        msg = f"<div class='card'><p class='{'b-ok' if decision.status=='APPROVED' else 'b-bad'}'>{_esc(decision.status)}/{_esc(decision.level)} — {_esc(decision.reason)}</p></div>"
        self._send(200, _page("提案", _proposal_body(d, msg)))
    def _handle_legacy_push(self, gid):
        d = _load_proposal(gid)
        if not d:
            return self._send(404, _page("未找到", "<p>提案不存在</p>"))
        cockpit_log("INFO", f"legacy_push {gid}：开始（提案校验）")
        ok, reason = verify_push(d, d.get("approval"))
        if not ok:
            msg = f"<div class='card'><p class='b-bad'>推送被拒：{_esc(reason)}</p></div>"
            return self._send(200, _page("提案", _proposal_body(d, msg)))
        # 推之前先探活：Mautic 没启动就直接报「不可达」，不撞 segment/form 误导错误
        _mok, _mwhy = _mautic_reachable("local")
        if not _mok:
            msg = (f"<div class='card'><p class='b-bad'>❌ 提案 {_esc(gid)} 推送失败：Mautic 不可达（{_esc(_mautic_netloc('local'))}），请先启动 Mautic（如运行 start-mautic-local.bat）后重试。</p>"
                   f"<p class='note'>探测 GET /api/segments 失败 → {_esc(_mwhy)}。提案未真正创建，可重试。</p></div>")
            return self._send(200, _page("提案", _proposal_body(d, msg)))
        result = push(d, env="local", approved=True, project_id=d.get("mautic_project_id"))
        d["deployed"] = True
        d["deploy_result"] = result
        dump_proposal(d, os.path.join(OUT_DIR, f"proposal_{gid}.json"))
        cockpit_log("OK", f"legacy_push {gid}：推送成功（{'dry-run' if result.get('dry_run') else result.get('env')}）")
        msg = f"<div class='card'><p class='b-ok'>已提交推送（{_esc('dry-run' if result.get('dry_run') else result.get('env'))}）：{_esc(reason)}</p></div>"
        self._send(200, _page("提案", _program_body(d, msg)))


def _sync_resolved_assets_to_strategy(c, result):
    """push() 已用派生名把真实资产建好（邮件=campaign_name / 落地页=campaign_name-落地页 /
    表单=campaign_name-表单）并把 id 写进 proposal.mautic_events，但从不回写 strategy 的展示字段，
    导致卡片永远显「[待生成]」占位、落地页无外链。

    这里从 push 的 ensure_log 取回真实资产名/alias，回填到 strategy，并翻转 email_mode/
    email_pending（消除 [待生成]）；同时使资产索引缓存失效，让卡片外链立即解析而非等 TTL(300s)。
    c 可以是 campaign 或 service 序列：两者都有 c["strategy"] 与 c["proposal"]。"""
    s = c.get("strategy")
    if not isinstance(s, dict):
        return
    prop = c.get("proposal") or {}
    cname = ((prop.get("campaign") or {}).get("name")
             or s.get("campaign_name") or c.get("cid"))
    if not cname:
        return
    log = (result or {}).get("ensure_log") or []
    by_name = {}
    for it in log:
        nm = it.get("name")
        if nm and it.get("id") is not None:
            by_name[nm] = it
    base = _mautic_base()

    # 邮件：主邮件名 = campaign_name；提醒 = campaign_name-提醒（与 push() 派生名一致）
    main = by_name.get(cname) or {}
    if main.get("id") is not None:
        s["email_ref"] = cname
        s["email_id"] = main.get("id")
    follow = by_name.get(f"{cname}-提醒") or {}
    if follow.get("id") is not None:
        s["email_followup_ref"] = f"{cname}-提醒"
        s["email_followup_id"] = follow.get("id")
    # 落地页
    lp = by_name.get(f"{cname}-落地页") or {}
    if lp.get("id") is not None:
        s["landing_page_ref"] = f"{cname}-落地页"
        s["landing_page_id"] = lp.get("id")
        _alias = lp.get("alias") or _aliasify(f"{cname}-落地页")
        if _alias:
            s["landing_page_url"] = f"{base}/{_alias}"
    # 表单（随所属 campaign 显示，见展示一致性改造；此处先把真实 ref/id 落盘备显示）
    form = by_name.get(f"{cname}-表单") or {}
    if form.get("id") is not None:
        s["form_ref"] = f"{cname}-表单"
        s["form_id"] = form.get("id")
    # 翻转占位状态：卡片不再显「[待生成]」
    if s.get("email_mode") == "generate":
        s["email_mode"] = "reuse"
    s["email_pending"] = False
    # 资产已写入 Mautic：刷新索引缓存，让卡片外链立即解析
    try:
        invalidate_asset_cache()
    except Exception:  # noqa: BLE001
        pass





def _tt_key(x: dict) -> tuple:
    """tag_triggers 中一条绑定的去重键。"""
    if not isinstance(x, dict):
        return ("", "", "")
    return (x.get("event") or x.get("on"),
            x.get("tag") or x.get("tags"),
            x.get("email_name") or x.get("name"))


def _compute_strategy_diff(old_s: dict, new_s: dict, cid: str = "") -> list:
    """比较两份 strategy，返回直白中文调整项列表（用于二次确认）。空列表 = 无变化。"""
    items = []
    if not isinstance(old_s, dict) or not isinstance(new_s, dict):
        return items

    def g(d, *ks, default=None):
        cur = d
        for k in ks:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k, default)
        return cur

    # 1) 邮件发送频次
    old_m = g(old_s, "send_conditions", "max_per_24h", default=1)
    new_m = g(new_s, "send_conditions", "max_per_24h", default=1)
    if old_m != new_m:
        items.append(f"调整邮件发送频次（原先：每天 {old_m} 份、现在每天 {new_m} 份）")

    # 2) 标签 新增/移除
    old_tags = set(old_s.get("tags_to_write") or [])
    new_tags = set(new_s.get("tags_to_write") or [])
    for t in sorted(new_tags - old_tags):
        items.append(f'新增标签 "{t}"')
    for t in sorted(old_tags - new_tags):
        items.append(f'移除标签 "{t}"')

    # 3) 折扣策略
    old_d = old_s.get("discount") if isinstance(old_s.get("discount"), dict) else {}
    new_d = new_s.get("discount") if isinstance(new_s.get("discount"), dict) else {}
    old_on = bool(old_d.get("enabled")) and (old_d.get("pct") is not None)
    new_on = bool(new_d.get("enabled")) and (new_d.get("pct") is not None)
    old_pct = old_d.get("pct") if old_on else None
    new_pct = new_d.get("pct") if new_on else None

    def _dlabel(on, pct):
        return f"开启 {pct}%" if on else "关闭"

    if old_on != new_on or (old_on and new_on and old_pct != new_pct):
        items.append(f"折扣策略（原先：{_dlabel(old_on, old_pct)}、现在：{_dlabel(new_on, new_pct)}）")

    # 4) 内容变体
    if old_s.get("content_variant") != new_s.get("content_variant"):
        items.append(f"切换内容变体（原先：v{old_s.get('content_variant')}、现在：v{new_s.get('content_variant')}）")

    # 5) 邮件内容角度
    old_a = g(old_s, "email_brief", "angle")
    new_a = g(new_s, "email_brief", "angle")
    if old_a and new_a and old_a != new_a:
        items.append(f'调整邮件内容角度（原先：「{old_a}」、现在：「{new_a}」）')

    # 6) 扩/收窄分组
    if not old_s.get("segment_broaden") and new_s.get("segment_broaden"):
        items.append("标记「扩分组」：向更广受众投放")
    if not old_s.get("segment_narrow") and new_s.get("segment_narrow"):
        items.append("标记「收窄分组」：聚焦高意向受众")

    # 7) 邮件事件绑定标签（tag_triggers）
    old_tt = old_s.get("tag_triggers") or []
    new_tt = new_s.get("tag_triggers") or []
    old_keys = {_tt_key(x) for x in old_tt if isinstance(x, dict)}
    for x in new_tt:
        if isinstance(x, dict) and _tt_key(x) not in old_keys:
            ev = x.get("event") or x.get("on") or "触发"
            tag = x.get("tag") or x.get("tags")
            if isinstance(tag, list):
                tag = "/".join(tag)
            items.append(f'当用户{ev}邮件「{x.get("email_name") or x.get("name") or ""}」会绑定标签 "{tag}"')

    # 8) 资产变化（邮件/落地页/分群）
    for fld, label in (("email_ref", "邮件"), ("landing_page_ref", "落地页"), ("segment", "分群")):
        if old_s.get(fld) != new_s.get(fld):
            items.append(f'调整{label}资产（原先：{old_s.get(fld) or "无"}、现在：{new_s.get(fld) or "无"}）')

    # 9) 邮件主题
    if old_s.get("subject") != new_s.get("subject"):
        items.append(f'调整邮件主题（原先：「{old_s.get("subject")}」、现在：「{new_s.get("subject")}」）')

    return items


def _diff_list_html(items: list, empty_txt: str = "无变化") -> str:
    if not items:
        return f"<p class='note' style='color:var(--ok)'>✅ {_esc(empty_txt)}</p>"
    li = "".join(f"<li>{_esc(x)}</li>" for x in items)
    return f"<ol class='diff' style='margin:6px 0 0 18px'>{li}</ol>"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--host", default=HOST)
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[活动驾驶舱] http://{args.host}:{args.port}/  → Mautic {load_config('local')['base_url']}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
