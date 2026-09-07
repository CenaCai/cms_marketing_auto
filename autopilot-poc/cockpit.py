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
  POST /program/<id>/complete                   标记某 campaign 完成 → 自适应改写下游
  GET  /proposal/<id>           遗留单 campaign 提案（run_poc 产出的）
  POST /proposal/<id>/approve|/push            遗留单 campaign 审批/推送
"""
from __future__ import annotations

import argparse
import html
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "output")

from goal_intake import parse_brief, GoalSpec
from plan_compiler import compile, dump_proposal
from approval_gate import (bind_and_approve, verify_push, is_valid,
                           ApprovalDecision)
from mautic_client import push, load_config, mautic_read_assets
from adaptive import (build_program, evaluate_and_replan, default_strategies,
                      DEFAULT_N_CAMPAIGNS, derive_plan, _split_windows)

PORT = 8090
HOST = "127.0.0.1"

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


# --------------------------- 工具 ---------------------------
def _esc(s) -> str:
    return html.escape(str(s))


def _program_path(gid: str) -> str:
    return os.path.join(OUT_DIR, f"program_{gid}.json")


def _load_program(gid: str):
    p = _program_path(gid)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_program(program: dict):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(_program_path(program["goal_id"]), "w", encoding="utf-8") as f:
        json.dump(program, f, ensure_ascii=False, indent=2)


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
CSS = """
:root{
 --bg:#f4f6f9; --card:#ffffff; --ink:#1c2330; --muted:#6b7280;
 --line:#e6e9ef; --brand:#185fa5; --brand-soft:#e8f1fb;
 --ok:#1d9e75; --ok-soft:#e1f5ee; --bad:#d85a30; --bad-soft:#fbece7;
 --warn:#ba7517; --warn-soft:#faefda; --gov:#3b6d11; --gov-soft:#eaf3de;
 --radius:14px; --shadow:0 1px 3px rgba(20,30,50,.06),0 6px 18px rgba(20,30,50,.05);
}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,"PingFang SC","Microsoft YaHei",sans-serif;
 background:var(--bg);color:var(--ink);font-size:14px;line-height:1.6}
.header{background:linear-gradient(180deg,#0f2a4a,#16406e);color:#fff;padding:18px 28px;display:flex;
 align-items:center;gap:14px;box-shadow:var(--shadow)}
.header .logo{font-size:18px;font-weight:600;letter-spacing:.5px}
.header .env{margin-left:auto;background:rgba(255,255,255,.14);padding:4px 12px;border-radius:999px;font-size:12px}
.wrap{max-width:1040px;margin:0 auto;padding:26px 20px 60px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
 padding:20px;margin-bottom:18px;box-shadow:var(--shadow)}
.grid2{display:grid;grid-template-columns:1.15fr .85fr;gap:18px}
@media(max-width:820px){.grid2{grid-template-columns:1fr}}
label{display:block;font-size:12px;color:var(--muted);margin:12px 0 5px;font-weight:500}
input,select,textarea{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:10px;
 font-size:14px;background:#fcfdff;color:var(--ink);font-family:inherit}
textarea{min-height:74px;resize:vertical;line-height:1.5}
input:focus,select:focus,textarea:focus{outline:2px solid var(--brand-soft);border-color:var(--brand)}
.btn{display:inline-block;background:var(--brand);color:#fff;padding:9px 16px;border-radius:10px;
 border:0;font-size:13px;cursor:pointer;text-decoration:none}
.btn.sec{background:var(--brand-soft);color:var(--brand)}
.btn.ghost{background:#fff;color:var(--brand);border:1px solid var(--line)}
.btn.sm{padding:5px 11px;font-size:12px}
.badge{display:inline-block;font-size:11px;padding:2px 9px;border-radius:999px;font-weight:600}
.b-ok{background:var(--ok-soft);color:var(--ok)} .b-bad{background:var(--bad-soft);color:var(--bad)}
.b-warn{background:var(--warn-soft);color:var(--warn)} .b-gov{background:var(--gov-soft);color:var(--gov)}
.b-idle{background:#eef0f3;color:#5f5e5a}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:6px;background:#eef0f3;color:#444;margin:1px}
.tag.gov{background:var(--gov-soft);color:var(--gov)} .tag.biz{background:var(--brand-soft);color:var(--brand)}
.tag.res{background:var(--warn-soft);color:var(--warn)}
code{background:#eef0f3;padding:1px 6px;border-radius:6px;font-size:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.pre{background:#0e1726;color:#cfe0f2;padding:13px;border-radius:10px;overflow:auto;font-size:12px}
a{color:var(--brand);text-decoration:none} a:hover{text-decoration:underline}
.agent{background:var(--gov-soft);border:1px dashed #b7d99a;border-radius:12px;padding:16px}
.agent h4{margin:0 0 10px;color:var(--gov);font-size:13px}
.agent .row{display:flex;flex-wrap:wrap;gap:7px}
.note{font-size:12px;color:var(--muted);margin-top:6px}
.pill{font-size:11px;color:var(--muted)}
"""

PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{css}</style></head>
<body><div class="header"><span class="logo">⚙ Autopilot 活动驾驶舱</span>
<span class="env">环境 local · → Mautic :8080</span></div>
<div class="wrap">{body}</div></body></html>"""


def _page(title: str, body: str) -> str:
    return PAGE.format(title=_esc(title), css=CSS, body=body)


# --------------------------- 页面 ---------------------------
def _dash_body() -> str:
    progs = _list_programs()
    if not progs:
        items = "<p class='sub'>暂无 Program。先 <a href='/brief'>填写一份 Brief</a> 发起目标。</p>"
    else:
        items = "<table><tr><th>Goal</th><th>campaign 数</th><th>各 campaign 状态</th><th></th></tr>"
        for p in progs:
            states = " ".join(
                f"<span class='badge {STATUS.get(c['status'], ('x','b-idle'))[1]}'>"
                f"{_esc(c['cid'].split('_c')[-1])}:{_esc(STATUS.get(c['status'], ('x',''))[0])}</span>"
                for c in p["campaigns"])
            items += (f"<tr><td><code>{_esc(p['goal_id'])}</code></td>"
                      f"<td>{p['n_campaigns']}</td><td>{states}</td>"
                      f"<td><a class='btn sec sm' href='/program/{_esc(p['goal_id'])}'>打开</a></td></tr>")
        items += "</table>"
    return (f"<h1>活动驾驶舱</h1><p class='sub'>一个目标 → 多个 campaign 自适应编排；"
            f"运营只填业务意图，治理/渠道/频次由 Agent 自动决策。</p>"
            f"<div class='card'><a class='btn' href='/brief'>+ 新建 Brief（发起目标）</a></div>"
            f"<div class='card'>{items}</div>")


def _brief_form(strategy_spec: list = None, spec_err: str = "", spec_meta: dict = None,
                service_spec: list = None) -> str:
    """
    运营只填「目标 + 约束」；分群/落库 tag/内容/频次等策略由 Agent 产出 StrategySpec。
    strategy_spec 非空时，右侧只读展示逐条策略摘要（供提交前确认）。
    """
    ex = {"objective": "", "locale": "zh_CN", "budget": "0", "start_date": "2028-05-01",
          "end_date": "2028-07-09", "overall_conv": "", "click_rate": "", "goal_name": ""}
    fld = lambda k, lbl, v, t="text", ph="": (f"<label>{lbl}</label><input name='{k}' type='{t}' value='{_esc(v)}' placeholder='{_esc(ph)}'>")
    operator = (f"<div class='card'><h3>① 你的目标与约束（运营填写）</h3>"
                f"<p class='note'>分群 / 内容 / 频次 / 落库 tag 由 Agent 在策略里产出，这里不填。</p>"
                f"{fld('objective','营销目标（一句话）',ex['objective'])}"
                f"{fld('goal_name','目标名称（便于阅读，如 UCL2028 票务预售）',ex['goal_name'])}"
                f"<div class='grid2'>"
                f"{fld('start_date','开始日期',ex['start_date'])}"
                f"{fld('end_date','结束日期',ex['end_date'])}</div>"
                f"<div class='grid2'>"
                f"{fld('overall_conv','总体目标转化率（最终期望，0~1，如 0.15）',ex['overall_conv'])}"
                f"{fld('click_rate','单 campaign 打开/点击率（0~1，如 0.30）',ex['click_rate'])}</div>"
                f"<div class='grid2'>"
                f"{fld('budget','预算金额（¥，留空或 0 = 无营收活动）',ex['budget'])}"
                f"<label>语言/地区</label>"
                f"<select name='locale'>"
                f"<option value='zh_CN' selected>中文</option>"
                f"<option value='en_US'>英文</option></select></div>"
                f"<p class='note'>无营收型活动（如品牌曝光 / 通知）会走更严格的审批门禁；有营收目标的活动填预算金额。</p>"
                f"<label>约束（红线 / 免打扰 / 合规要求，一行一条）</label>"
                f"<textarea name='constraints' placeholder='例：22:00-09:00 免打扰&#10;不得对已购票用户重复触达'></textarea>"
                f"<label>策略规格（Agent 产出，可选）</label>"
                f"<div class='note'><ul>"
                f"<li>这是什么：由 Agent 根据目标产出的多波次策略文件，包含分群 / 邮件 / 频次 / 落库 tag。</li>"
                f"<li>怎么填：可填多个路径（逗号或换行分隔，如 <code>strategies/a.json, strategies/b.json</code>），"
                f"也可直接粘贴 JSON，也可留空。</li>"
                f"<li>留空 = 使用默认递进策略（分波延迟递增、内容变体递增）。</li>"
                f"</ul></div>"
                f"<textarea name='strategy_spec' placeholder='strategies/ucl2028_send_strategy.json, strategies/ucl2028_content_map.json'>"
                f"{_esc('strategies/example_strategy.json' if strategy_spec else '')}</textarea>"
                f"<div id='plan-preview' class='note'>填写总体转化率与单 campaign 点击率后，将自动预览派生的战役数量与执行窗口。</div>"
                f"<button class='btn' type='submit' style='margin-top:14px'>编译并生成 Program →</button>"
                f"</div>"
                f"<script>"
                f"(function(){{"
                f"function derive(){{"
                f"  var oc=parseFloat(document.querySelector(\"[name=overall_conv]\").value)||0;"
                f"  var cr=parseFloat(document.querySelector(\"[name=click_rate]\").value)||0;"
                f"  var sd=document.querySelector(\"[name=start_date]\").value;"
                f"  var ed=document.querySelector(\"[name=end_date]\").value;"
                f"  var LP=0.10, n=3, target=0;"
                f"  if(oc>0 && cr>0){{"
                f"    var pc=cr*LP;"
                f"    if(pc>0 && pc<1){{ n=Math.max(1,Math.min(8,Math.ceil(Math.log(1-oc)/Math.log(1-pc)))); }}"
                f"    else {{ n=1; }}"
                f"    target=Math.round(oc/n*10000)/10000;"
                f"  }}"
                f"  var rows='';"
                f"  try{{"
                f"    var s=new Date(sd), e=new Date(ed), span=Math.max(0,(e-s)/86400000), step=span/n;"
                f"    for(var i=0;i<n;i++){{"
                f"      var ws=new Date(s.getTime()+step*i*86400000);"
                f"      var we=(i<n-1)?new Date(s.getTime()+step*(i+1)*86400000):e;"
                f"      var f=function(x){{return x.toISOString().slice(0,10);}};"
                f"      rows+='<tr><td>'+(i+1)+'</td><td>'+f(ws)+' ~ '+f(we)+'</td><td>'+target+'</td></tr>';"
                f"    }}"
                f"  }}catch(err){{ rows='<tr><td colspan=3>请同时填写开始 / 结束日期</td></tr>'; }}"
                f"  var el=document.getElementById('plan-preview');"
                f"  if(oc>0||cr>0){{"
                f"    el.innerHTML='<h4 style=\"margin:6px 0\">自动派生计划预览</h4><p class=\"note\">将生成 '+n+' 个战役</p>"
                f"<table><tr><th>战役</th><th>执行窗口</th><th>转化目标</th></tr>'+rows+'</table>';"
                f"  }} else {{"
                f"    el.innerHTML='填写总体转化率与单 campaign 点击率后，将自动预览派生的战役数量与执行窗口。';"
                f"  }}"
                f"}}"
                f"['overall_conv','click_rate','start_date','end_date'].forEach(function(nm){{"
                f"  var el=document.querySelector('[name='+nm+']'); if(el){{ el.addEventListener('input', derive); }}"
                f"}});"
                f"derive();"
                f"}})();"
                f"</script>")
    agent = ("<div class='agent'><h4>② Agent 自动决策（运营无需、也不能改）</h4>"
             "<div class='row'>"
             "<span class='tag biz'>主渠道 email（MVP 裁定）</span>"
             "<span class='tag res'>预留 sms（占位不发）</span>"
             "<span class='tag gov'>频次闸门 1/24h·3/7d</span>"
             "<span class='tag gov'>护栏 退订熔断0.3%·尊重抑制名单</span>"
             "<span class='tag gov'>治理注入 4 节点</span>"
             "<span class='tag gov'>mtc_* 追踪 + 9 埋点</span>"
             "<span class='tag gov'>plan_hash 绑定审批·篡改即拒</span>"
             "</div><p class='note'>这些由合并规格的治理策略与 MVP 裁定确定性生成，"
             "不由运营编辑，避免合规/频次被误改。</p>"
             + _spec_preview_html(strategy_spec, spec_err, spec_meta)
             + _service_preview_html(service_spec)
             + "</div>")
    return f"<h1>新建 Brief</h1><p class='sub'>方案 A 驾驶舱 · 独立 :8090 → Mautic :8080</p>" \
           f"<form method='post' action='/brief'><div class='grid2'>{operator}{agent}</div></form>"


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


def _strategy_summary(s: dict) -> str:
    """Program 页每 campaign 的策略摘要：理由/依据/分群/邮件/变体/发送条件/tag。"""
    s = s or {}
    sc = s.get("send_conditions", {}) or {}
    cv = s.get("content_variant_spec") or {}
    tags = " ".join(f"<span class='tag'>{_esc(t)}</span>" for t in s.get("tags_to_write", [])) or "—"
    base = (f"分群 <code>{_esc(s.get('segment',''))}</code>"
            f"<span class='pill'>({_esc(s.get('segment_mode','reuse'))})</span>"
            f" · 频 <code>{sc.get('max_per_24h',1)}/24h·{sc.get('max_per_7d',3)}/7d</code>"
            f" · 延迟 <code>{sc.get('delay_hours',24)}h</code>"
            f"{(' · 免打扰 <code>' + _esc(sc['quiet_hours']) + '</code>') if sc.get('quiet_hours') else ''}"
            f" · 邮件 <code>{_esc(email_display(s))}</code>"
            f" · 落页 <code>{_esc(s.get('landing_page_ref','') or '—')}</code>"
            f" · 变体 <code>{_esc(cv.get('id') or ('v%s' % s.get('content_variant',0)))}</code>"
            f" {_esc(cv.get('angle') or '')}"
            f"{((' — ' + _esc(cv['headline'])) if cv.get('headline') else '')}"
            f" · tag {tags}")
    why = ""
    if s.get("rationale") or s.get("evidence"):
        why = (f"<br><span class='pill'>理由：{_esc(s.get('rationale') or '—')}"
               f" ｜ 依据：{_esc(s.get('evidence') or '—')}</span>")
    return base + why


def _graph_svg(graph: list) -> str:
    """把事件图渲染成依赖无关的 inline SVG 流程图（左→右排布，>6 节点换行）。"""
    import math as _m
    nodes = list(graph)
    if not nodes:
        return "<p class='note'>（事件图为空）</p>"
    COLS, W, H = 6, 110, 56
    GAPX, GAPY, PADX, PADY = 46, 34, 16, 16
    rows = _m.ceil(len(nodes) / COLS)
    vw = PADX * 2 + COLS * W + (COLS - 1) * GAPX
    vh = PADY * 2 + rows * H + (rows - 1) * GAPY
    pos = {}
    for i, nd in enumerate(nodes):
        r, cidx = divmod(i, COLS)
        pos[nd["id"]] = (PADX + cidx * (W + GAPX), PADY + r * (H + GAPY))

    def _short(t: str) -> str:
        # 取类型末两段，保证可读（decision.segment → segment；email.send → send）
        parts = t.split(".")
        return parts[-1] if len(parts) == 1 else ".".join(parts[-2:])

    def _color(nd: dict):
        t = nd.get("type", "")
        if nd.get("governance") or t.endswith(".reserved"):
            return "#3b6d11", "#eaf3de"      # 治理/预留：绿
        if t.startswith("decision"):
            return "#ba7517", "#faefda"      # 决策：橙
        return "#185fa5", "#e8f1fb"          # 业务：蓝

    svg = [f"<svg viewBox='0 0 {vw} {vh}' width='100%' "
           f"style='background:#fbfcfe;border:1px solid var(--line);border-radius:10px' "
           f"font-family='inherit' font-size='11'>"]
    svg.append("<defs><marker id='arw' markerWidth='8' markerHeight='8' refX='6' refY='3' "
               "orient='auto' markerUnits='userSpaceOnUse'>"
               "<path d='M0,0 L6,3 L0,6 Z' fill='#6b7280'/></marker>"
               "<marker id='arwok' markerWidth='8' markerHeight='8' refX='6' refY='3' "
               "orient='auto' markerUnits='userSpaceOnUse'>"
               "<path d='M0,0 L6,3 L0,6 Z' fill='#1d9e75'/></marker>"
               "<marker id='arwbad' markerWidth='8' markerHeight='8' refX='6' refY='3' "
               "orient='auto' markerUnits='userSpaceOnUse'>"
               "<path d='M0,0 L6,3 L0,6 Z' fill='#d85a30'/></marker></defs>")
    # 连线
    for nd in nodes:
        x, y = pos[nd["id"]]
        for key, stroke, mk in (("next", "#6b7280", "url(#arw)"),
                                 ("if_true", "#1d9e75", "url(#arwok)"),
                                 ("if_false", "#d85a30", "url(#arwbad)")):
            if key in nd:
                tgt = pos.get(nd[key])
                if not tgt:
                    continue
                tx, ty = tgt
                x1, y1 = x + W, y + H / 2
                x2, y2 = tx, ty + H / 2
                dash = " stroke-dasharray='4 3'" if key == "if_false" else ""
                svg.append(f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' "
                           f"stroke='{stroke}'{dash} stroke-width='1.4' marker-end='{mk}'/>")
    # 节点
    for nd in nodes:
        x, y = pos[nd["id"]]
        fill, stroke = _color(nd)
        svg.append(f"<g><title>{_esc(nd['type'])}</title>"
                   f"<rect x='{x}' y='{y}' width='{W}' height='{H}' rx='9' "
                   f"fill='{stroke}' stroke='{fill}' stroke-width='1.5'/>"
                   f"<text x='{x + W/2}' y='{y + 20}' text-anchor='middle' "
                   f"fill='{fill}' font-weight='600'>{_esc(_short(nd['type']))}</text>"
                   f"<text x='{x + W/2}' y='{y + 38}' text-anchor='middle' "
                   f"fill='#1c2330' font-size='9'>{_esc(nd['id'])}</text></g>")
    svg.append("</svg>")
    return "".join(svg)


def _mautic_asset_table(program: dict) -> str:
    """汇总 Program 内每个 campaign 引用/将新建的 Mautic 资产（新建 vs 调用已有）。"""
    env = mautic_read_assets("local")
    avail = env.get("available", False)
    emails = {str(x.get("name")): x for x in env.get("emails", [])}
    email_ids = {str(x.get("id")): x for x in env.get("emails", [])}
    segs = {str(x.get("name")): x for x in env.get("segments", [])}
    seg_ids = {str(x.get("id")): x for x in env.get("segments", [])}
    pages = {str(x.get("name")): x for x in env.get("pages", [])}
    page_alias = {str(x.get("alias")): x for x in env.get("pages", [])}

    def _exists(ref: str, name_map: dict, id_map: dict) -> bool:
        if not ref:
            return False
        return ref in name_map or ref in id_map

    def _row(kind, ref, mode):
        if not ref:
            ref = "（无）"
        if mode == "generate":
            concl = "新建"
        else:
            concl = "调用已有"
        if avail and ref not in ("（无）",):
            real = "✓" if _exists(ref,
                                  emails if kind == "email" else segs if kind == "分群" else pages,
                                  email_ids if kind == "email" else seg_ids if kind == "分群" else page_alias) \
                else "✗"
        elif avail:
            real = "—"
        else:
            real = "未连"
        return (f"<tr><td>{kind}</td><td><code>{_esc(ref)}</code></td>"
                f"<td>{_esc(mode)}</td><td>{concl}</td><td>{real}</td></tr>")

    rows = ""
    for c in program["campaigns"]:
        s = c["strategy"]
        em_ref = s.get("email_ref", "")
        em_mode = s.get("email_mode", "reuse")
        seg = s.get("segment", "")
        seg_mode = s.get("segment_mode", "reuse")
        lp = s.get("landing_page_ref", "")
        rows += _row("email", em_ref, em_mode)
        rows += _row("分群", seg, seg_mode)
        if lp:
            rows += _row("着陆页", lp, "reuse")
        else:
            rows += ("<tr><td>着陆页</td><td><code>—</code></td><td>generate</td>"
                     "<td>新建</td><td>未连</td></tr>" if not avail else
                     "<tr><td>着陆页</td><td><code>—</code></td><td>generate</td>"
                     "<td>新建</td><td>✗</td></tr>")
    note = ("（未连接 Mautic 或缺少凭证：以下为基于策略规格的预期清单）" if not avail
            else "（已连接 Mautic，✓=实存 / ✗=策略引用但 Mautic 中不存在）")
    return (f"<div class='card'><h3>Mautic 资产清单（新建 vs 调用）</h3>"
            f"<p class='note'>{_esc(note)}</p>"
            f"<table><tr><th>类型</th><th>引用(ref)</th><th>模式</th>"
            f"<th>结论</th><th>实存</th></tr>{rows}</table></div>")


def _program_body(program: dict, msg: str = "") -> str:
    gid = program["goal_id"]
    goal = program["goal"]
    # 自适应规则说明
    rules = ("<p class='note'>自适应规则（确定性，可审计）：上游完成后按「达成率/退订率」改写下游 —— "
             "达标→保持略降本；未达标(≥50%)→提频+换内容+urgency；乏力→大幅提频+扩分组(broaden/reengage)+换内容；"
             "退订超阈→降频+suppression。</p>")
    # campaign 流水线
    cards = ""
    campaigns = program["campaigns"]
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
        approve_f = (f"<form method='post' action='/program/{gid}/campaign/{c['cid']}/approve' "
                     f"style='margin:8px 0'>"
                     f"<input name='approver' placeholder='审批人(真人)' style='width:160px;display:inline-block'>"
                     f"{ack_c}<button class='btn sm' type='submit'>审批通过</button></form>")
        push_f = (f"<form method='post' action='/program/{gid}/campaign/{c['cid']}/push' style='display:inline'>"
                  f"<button class='btn sm sec' type='submit'>推送</button></form>" if ap else
                  "<span class='pill'>需先审批</span>")
        # 新阶段创建按钮（#8）：已审批且（首波 / 上一波已完成并回填结果）才可点
        create_f = ""
        if ap and st not in ("executing", "approved_idle", "done_met", "done_below"):
            if i == 0:
                create_f = (f"<form method='post' action='/program/{gid}/campaign/{c['cid']}/create' "
                            f"style='display:inline;margin-left:6px'>"
                            f"<button class='btn sm sec' type='submit'>创建并推送到 Mautic</button></form>")
            else:
                prev = campaigns[i - 1]
                if prev["status"] in ("done_met", "done_below") and prev.get("feedback"):
                    create_f = (f"<form method='post' action='/program/{gid}/campaign/{c['cid']}/create' "
                                f"style='display:inline;margin-left:6px'>"
                                f"<button class='btn sm sec' type='submit'>确认开启下一个 →</button></form>")
                else:
                    create_f = "<span class='pill'>（上一波完成并回填结果后才可创建）</span>"
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
        # 执行结果回填（#8，人工喂养，不自动推进）
        feedback_f = (f"<form method='post' action='/program/{gid}/campaign/{c['cid']}/feedback' "
                      f"style='margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;align-items:center'>"
                      f"<input name='sent' placeholder='发送数' style='width:84px;display:inline-block'>"
                      f"<input name='opened' placeholder='打开数' style='width:84px;display:inline-block'>"
                      f"<input name='converted' placeholder='转化数' style='width:84px;display:inline-block'>"
                      f"<input name='unsub' placeholder='退订数' style='width:84px;display:inline-block'>"
                      f"<button class='btn sm ghost' type='submit'>回填执行结果</button></form>")
        fb = c.get("feedback") or {}
        fb_txt = ""
        if fb:
            fb_txt = (f"<span class='pill'>回填：发送 {fb.get('sent')} · 打开 {fb.get('opened')} · "
                      f"转化 {fb.get('converted')}（达成率 {fb.get('conv_rate')}） · "
                      f"退订 {fb.get('unsub')}（退订率 {fb.get('unsub_rate')}）</span>")
        complete_f = (f"<form method='post' action='/program/{gid}/complete' style='margin-top:8px'>"
                      f"<input type='hidden' name='cid' value='{_esc(c['cid'])}'>"
                      f"<input name='conversion' placeholder='达成率0~1（留空用回填）' style='width:150px;display:inline-block'>"
                      f"<input name='unsub' placeholder='退订率0~1' style='width:120px;display:inline-block'>"
                      f"<button class='btn sm ghost' type='submit'>标记完成并回写达成 → 改写下游</button></form>")
        result_txt = ""
        if c.get("result"):
            result_txt = (f"<span class='pill'>达成 {c['result'].get('conversion')} · "
                          f"退订 {c['result'].get('unsub')}</span>")
        cards += (f"<div class='card'><div style='display:flex;justify-content:space-between;align-items:center'>"
                  f"<strong>{_esc(c['wave_id'])} · <code>{_esc(c['cid'])}</code></strong>{st_badge}</div>"
                  f"<p style='margin:8px 0'>{_strategy_summary(c['strategy'])}</p>"
                  f"<p class='pill'>plan_hash <code>{_esc(prop['plan_hash'][:14])}</code> · 审批 {ap_txt} {result_txt}</p>"
                  f"{goals_txt}{fb_txt}"
                  f"<details><summary class='pill'>事件图（{len(prop['graph'])} 节点 · 流程图）</summary>"
                  f"{_graph_svg(prop['graph'])}</details>"
                  f"{defer_note}{qh_c}{approve_f}{push_f}{create_f}{defer_f}{goals_f}{feedback_f}{complete_f}</div>")
    # Mautic 资产清单（新建 vs 调用已有）—— 整 Program 汇总（#6）
    cards += _mautic_asset_table(program)
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
                f"变体 <code>{_esc((s['strategy'].get('content_variant_spec') or {}).get('id',''))}</code></p>"
                f"<p class='pill'>豁免：{_esc('；'.join(f'{k}' for k in ex) or '—')}</p>"
                f"<p class='pill'>治理节点：{_esc(', '.join(gtypes))}</p>"
                f"<p class='pill'>plan_hash <code>{_esc(prop['plan_hash'][:14])}</code> · 审批 {ap3_txt}</p>"
                f"{qh}"
                f"<details><summary class='pill'>事件图（{len(prop['graph'])} 节点 · 流程图）</summary>"
                f"{_graph_svg(prop['graph'])}</details>"
                f"{approve3_f}{push3_f}</div>")
    if svc:
        svc = ("<div class='card' style='background:var(--gov-soft)'><h3>服务序列（service/transactional）</h3>"
               "<p class='note'>与 promo Program 解耦：不注入频次闸门/锚点仲裁，豁免 suppress_promo 与 comm_freeze，"
               "不占 promo 配额、不计入每人触达上限。</p></div>" + svc)
    # changelog
    clog = ""
    if program.get("changelog"):
        clog = "<div class='card'><h3>自适应变更记录</h3>"
        for e in program["changelog"]:
            lines = "".join(
                f"<li><code>{_esc(ch['cid'])}</code>：{'；'.join(ch['notes'])} "
                f"<span class='pill'>→ plan_hash {_esc(ch['plan_hash'][:12])}</span></li>"
                for ch in e["changes"])
            clog += (f"<p><strong>上游 {_esc(e['completed_cid'])} 完成</strong> · 达成率 "
                     f"{_esc('未设置（R 未给）' if e.get('target_unset') else e.get('ratio'))} · "
                     f"结果 {_esc(e['result'])}</p><ul>{lines}</ul>")
        clog += "</div>"
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
    header_html = (f"<h1>Program {_esc(gid)}</h1>"
                   f"<p class='sub'>目标名称：{_esc(goal_name) if goal_name else '（未命名）'} "
                   f"（ID: {_esc(gid)}）<br>"
                   f"{_esc(goal.get('objective',''))} · 渠道 {_esc(','.join(goal.get('channels',[])))}"
                   f" · {program['n_campaigns']} 个 campaign"
                   f"{(' + ' + str(program.get('n_service_sequences', 0)) + ' 条服务序列') if program.get('n_service_sequences') else ''}"
                   f" · 策略来源 {src_html}</p>")
    return (f"{msg}{header_html}"
            f"{kpi_html}{cons_html}<div class='card'>{rules}</div>{cards}{svc}{clog}")


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


def _resolve_strategy_spec(src: str):
    """解析 StrategySpec（文件路径或 JSON 文本）→ (campaigns, service_sequences, err, meta)。"""
    try:
        spec = parse_strategy_spec(src)
    except Exception as e:  # noqa: BLE001
        return [], [], str(e), None
    campaigns = strategies_from_spec(spec)
    services = service_sequences_from_spec(spec)
    meta = spec_goal_defaults(spec)
    if not campaigns and not services:
        return [], [], "StrategySpec 的 campaigns / service_sequences 均为空", meta
    return campaigns, services, "", meta


# --------------------------- Handler ---------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

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

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", ""):
            return self._send(200, _page("驾驶舱", _dash_body()))
        if path == "/brief":
            # 支持 /brief?spec=<StrategySpec 文件路径> 预览 Agent 策略（只读）
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            spec_src = (q.get("spec") or [""])[0].strip()
            strategies, services, err, meta = [], [], "", None
            if spec_src:
                strategies, services, err, meta = _resolve_strategy_spec(spec_src)
            return self._send(200, _page("新建 Brief", _brief_form(strategies, err, meta, services)))
        if path.startswith("/program/"):
            gid = path[len("/program/"):]
            p = _load_program(gid)
            if not p:
                return self._send(404, _page("未找到", "<p class='b-bad'>Program 不存在</p>"))
            return self._send(200, _page("Program", _program_body(p)))
        if path.startswith("/proposal/"):
            gid = path[len("/proposal/"):]
            d = _load_proposal(gid)
            if not d:
                return self._send(404, _page("未找到", "<p>提案不存在</p>"))
            return self._send(200, _page("提案", _proposal_body(d)))
        return self._send(404, _page("404", "<p>未知路径</p>"))

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        form = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

        if path == "/brief":
            return self._handle_brief(form)
        if path.endswith("/approve") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._handle_campaign_approve(gid, cid, form)
        if path.endswith("/push") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._handle_campaign_push(gid, cid)
        if path.endswith("/activate") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._handle_campaign_activate(gid, cid)
        if path.endswith("/goals") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._handle_campaign_goals(gid, cid, form)
        if path.endswith("/create") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._handle_campaign_create(gid, cid)
        if path.endswith("/feedback") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._handle_campaign_feedback(gid, cid, form)
        if path.endswith("/complete"):
            return self._handle_complete(form)
        if path.endswith("/approve") and "/service/" in path:
            parts = [x for x in path.split("/") if x]
            return self._handle_service_approve(parts[1], parts[3], form)
        if path.endswith("/push") and "/service/" in path:
            parts = [x for x in path.split("/") if x]
            return self._handle_service_push(parts[1], parts[3])
        if path.endswith("/approve"):
            gid = path.split("/")[-2]
            return self._handle_legacy_approve(gid, form)
        if path.endswith("/push"):
            gid = path.split("/")[-2]
            return self._handle_legacy_push(gid)
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
                strategies, services, spec_err, spec_meta = _resolve_strategy_spec(spec_src)
            else:
                strategies, services, spec_err, spec_meta = [], [], "", None
            if spec_err:
                raise ValueError(f"StrategySpec 解析失败：{spec_err}")
            d = spec_meta or {}

            # N 由策略数组长度决定；未提交策略时由 derive_plan 派生（总体转化率 + 点击率）
            overall_conv = (form.get("overall_conv", "") or "").strip()
            click_rate = (form.get("click_rate", "") or "").strip()
            plan_raw = derive_plan(overall_conv, click_rate,
                                   form.get("start_date", "") or d.get("start_date", ""),
                                   form.get("end_date", "") or d.get("end_date", ""))
            n = len(strategies) if strategies else plan_raw["n_campaigns"]
            # 执行窗口按真实 campaign 数均分（派生 n 与策略 n 可能不同）
            n_actual = len(strategies) if strategies else plan_raw["n_campaigns"]
            sd_raw = (form.get("start_date", "") or d.get("start_date", "")).strip()
            ed_raw = (form.get("end_date", "") or d.get("end_date", "")).strip()
            windows = (_split_windows(sd_raw, ed_raw, n_actual)
                       if sd_raw and ed_raw else
                       [{"start": sd_raw, "end": ed_raw} for _ in range(n_actual)])
            plan = {"n_campaigns": n_actual, "windows": windows,
                    "per_campaign_target": plan_raw["per_campaign_target"]}

            # ---- L0：运营只填目标与约束，其余由 Agent 策略补 ----
            locale_raw = (form.get("locale", "") or d.get("locale", "zh_CN") or "zh_CN").strip()
            # 表单 locale 为单选下拉（中文/英文），直接取单值
            locales = [locale_raw] if locale_raw else (d.get("locales") or ["zh_CN"])
            constraints = [ln.strip() for ln in
                           (form.get("constraints", "") or "").splitlines() if ln.strip()]
            goal_name = (form.get("goal_name", "") or "").strip()
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
                "start_date": (form.get("start_date", "") or d.get("start_date", "")).strip(),
                "end_date": (form.get("end_date", "") or d.get("end_date", "")).strip(),
                "channels": ["email"], "reserved_channels": ["sms"],
                "goal_id": d.get("goal_id", ""),
            }
            if not raw["goal_id"]:
                raw.pop("goal_id")
            goal = parse_brief(raw)
            if goal_name:
                goal.name = goal_name
            goal.meta = {
                "locales": locales or d.get("locales", []),
                "constraints": constraints,
                "name": goal_name,
                "strategy_source": (strategies[0].get("strategy_source", "default")
                                    if strategies else "default"),
            }
            program = build_program(goal, n, compile, strategy_spec=strategies or None,
                                    service_sequences=services or None)
            # 每个 campaign 绑定派生计划：转化目标 + 执行窗口（可在 /program 上编辑）
            for i, c in enumerate(program["campaigns"]):
                w = windows[i] if i < len(windows) else {"start": sd_raw, "end": ed_raw}
                c["conv_target"] = plan_raw["per_campaign_target"]
                c["unsub_cap"] = 0.003
                c["exec_start"] = w["start"]
                c["exec_end"] = w["end"]
            program["constraints"] = constraints
            program["plan"] = plan
            _save_program(program)
            self.send_response(302)
            self.send_header("Location", f"/program/{goal.goal_id}")
            self.end_headers()
        except Exception as e:  # noqa: BLE001
            self._send(200, _page("Brief 错误", f"<p class='b-bad'>{_esc(e)}</p><p><a href='/brief'>返回</a></p>"))

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
        ok, reason = verify_push(s["proposal"], s["proposal"].get("approval"))
        if not ok:
            msg = f"<div class='card'><p class='b-bad'>推送被拒：{_esc(reason)}</p></div>"
            return self._send(200, _page("Program", _program_body(p, msg)))
        result = push(s["proposal"], env="local", approved=True)
        s["proposal"]["deployed"] = True
        s["proposal"]["deploy_result"] = result
        _save_program(p)
        msg = (f"<div class='card'><p class='b-ok'>服务序列已提交推送"
               f"（{_esc('dry-run' if result.get('dry_run') else result.get('env'))}）：{_esc(reason)}</p></div>")
        self._send(200, _page("Program", _program_body(p, msg)))

    def _handle_campaign_push(self, gid, cid):
        p = _load_program(gid)
        if not p:
            return self._send(404, _page("未找到", "<p>Program 不存在</p>"))
        c = next((x for x in p["campaigns"] if x["cid"] == cid), None)
        if not c:
            return self._send(404, _page("未找到", "<p>campaign 不存在</p>"))
        ok, reason = verify_push(c["proposal"], c["proposal"].get("approval"))
        if not ok:
            msg = f"<div class='card'><p class='b-bad'>推送被拒：{_esc(reason)}</p></div>"
            return self._send(200, _page("Program", _program_body(p, msg)))
        if c["status"] == "deferred":
            msg = ("<div class='card'><p class='b-bad'>推送被拒：该波为 deferred（外部事件触发），"
                   "请先由运营启用</p></div>")
            return self._send(200, _page("Program", _program_body(p, msg)))
        result = push(c["proposal"], env="local", approved=True)
        c["proposal"]["deployed"] = True
        c["proposal"]["deploy_result"] = result
        _save_program(p)
        msg = f"<div class='card'><p class='b-ok'>已提交推送（{_esc('dry-run' if result.get('dry_run') else result.get('env'))}）：{_esc(reason)}</p></div>"
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
        c["status"] = "approved_idle"   # 已审核-未执行：草稿已在 Mautic，待发布执行
        _save_program(p)
        result = push(c["proposal"], env="local", approved=True)
        c["proposal"]["deployed"] = True
        c["proposal"]["deploy_result"] = result
        c["status"] = "executing"        # 推送已发布 → 执行中
        _save_program(p)
        note = "dry-run" if result.get("dry_run") else result.get("env")
        msg = (f"<div class='card'><p class='b-ok'>{_esc(cid)} 已创建并推送到 Mautic（{_esc(note)}），"
               f"状态：执行中。{_esc('（未填凭证，仅 dry-run）' if result.get('dry_run') else '')}</p></div>")
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

    def _handle_complete(self, form):
        # path 形如 /program/<gid>/complete
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
        out = evaluate_and_replan(p, cid, result)
        if "error" in out:
            msg = f"<div class='card'><p class='b-bad'>{_esc(out['error'])}</p></div>"
            return self._send(200, _page("Program", _program_body(p, msg)))
        _save_program(p)
        changed = "; ".join(f"{ch['cid']}:{'/'.join(ch['notes'])}" for ch in out["changes"]) or "无下游待改写"
        ratio_txt = ("未设置（KPI 目标 R 未给，不做达成率改写）" if out.get("target_unset")
                     else str(out["ratio"]))
        done_lbl = STATUS.get(p and next((x["status"] for x in p["campaigns"] if x["cid"] == cid), ""), ("", ""))[0]
        msg = (f"<div class='card'><p class='b-ok'>上游 {_esc(cid)} 完成（{_esc(done_lbl)}），"
               f"达成率 {_esc(ratio_txt)} → 下游改写：{_esc(changed)}</p></div>")
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
        ok, reason = verify_push(d, d.get("approval"))
        if not ok:
            msg = f"<div class='card'><p class='b-bad'>推送被拒：{_esc(reason)}</p></div>"
            return self._send(200, _page("提案", _proposal_body(d, msg)))
        result = push(d, env="local", approved=True)
        d["deployed"] = True
        d["deploy_result"] = result
        dump_proposal(d, os.path.join(OUT_DIR, f"proposal_{gid}.json"))
        msg = f"<div class='card'><p class='b-ok'>已提交推送（{_esc('dry-run' if result.get('dry_run') else result.get('env'))}）：{_esc(reason)}</p></div>"
        self._send(200, _page("提案", _program_body(d, msg)))


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
