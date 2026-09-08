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
from mautic_client import (push, load_config, mautic_read_assets,
                           mautic_read_campaigns, mautic_get_campaign,
                           auto_feedback_for_campaign)
from adaptive import (build_program, evaluate_and_replan, default_strategies,
                      DEFAULT_N_CAMPAIGNS, derive_plan, _split_windows,
                      ASSUMED_LP_CONV)

# 与 adaptive.derive_plan 一致的策略阈值（Agent 可达性校验用）
RC_MAX = 0.50

PORT = 8090
HOST = "127.0.0.1"

# 多选表单字段（提交时同名多值，后端按 list 解析）
MULTI_FORM_FIELDS = {"audience_age", "audience_gender", "audience_income",
                     "audience_education", "audience_industry",
                     "audience_source", "audience_region", "locale"}

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


def _yesterday_str() -> str:
    import datetime as _dt
    return (_dt.date.today() - _dt.timedelta(days=1)).strftime("%Y-%m-%d")


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
.req{color:#c0392b;font-weight:700;margin-right:2px}  /* 必填星号 */
.opt{color:#7f8896;font-size:11px;font-weight:500;margin-left:2px}  /* 可选小标 */
/* 多选 chip 选择器（替代原生 select multiple） */
.chip-group{display:flex;flex-wrap:wrap;gap:8px;padding:3px 0 13px;border-bottom:1px dashed #d3d9e2}
.chip{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border:1px solid var(--line);
 border-radius:999px;background:#fcfdff;font-size:13px;line-height:1;cursor:pointer;user-select:none;
 transition:border-color .12s,background .12s,color .12s}
.chip:hover{border-color:var(--brand);background:var(--brand-soft)}
.chip input{display:none}
.chip:has(input:checked){background:var(--brand);border-color:var(--brand);color:#fff;font-weight:600}
/* 营销目标「最近填写」历史下拉 */
.obj-history{position:relative;background:#fff;border:1px solid var(--line);border-radius:10px;
 margin-top:4px;box-shadow:var(--shadow);z-index:20;max-height:210px;overflow:auto}
.obj-hist-empty{padding:7px 12px;color:var(--muted);font-size:12px;border-bottom:1px solid #f0f2f5}
.obj-hist-item{padding:8px 12px;font-size:13px;cursor:pointer;border-bottom:1px solid #f0f2f5}
.obj-hist-item:last-child{border-bottom:0}
.obj-hist-item:hover{background:var(--brand-soft);color:var(--brand)}
/* KPI 看板 (issue 2026-09-07) */
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:8px 0}
.kpi-card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px;text-align:center;position:relative;overflow:hidden}
.kpi-card::before{content:'';position:absolute;top:0;left:0;right:0;height:4px;background:var(--brand)}
.kpi-card.gov::before{background:var(--gov)} .kpi-card.warn::before{background:var(--warn)}
.kpi-card.ok::before{background:var(--ok)} .kpi-card.bad::before{background:var(--bad)}
.kpi-num{font-size:30px;font-weight:700;line-height:1.1;color:var(--ink);margin:6px 0 2px}
.kpi-card.gov .kpi-num{color:var(--gov)} .kpi-card.warn .kpi-num{color:var(--warn)}
.kpi-card.ok .kpi-num{color:var(--ok)} .kpi-card.bad .kpi-num{color:var(--bad)}
.kpi-label{font-size:12px;color:var(--muted);font-weight:500}
.kpi-sub{font-size:10px;color:var(--muted);margin-top:3px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:6px;background:#eef0f3;color:#444;margin:1px}
.tag.gov{background:var(--gov-soft);color:var(--gov)} .tag.biz{background:var(--brand-soft);color:var(--brand)}
.tag.res{background:var(--warn-soft);color:var(--warn)}
code{background:#eef0f3;padding:1px 6px;border-radius:6px;font-size:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.pre{background:#0e1726;color:#cfe0f2;padding:13px;border-radius:10px;overflow:auto;font-size:12px}
a{color:var(--brand);text-decoration:none} a:hover{text-decoration:underline}
.ext{font-weight:600} .ext::after{content:" ↗";font-weight:400}
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
        if(navigator.clipboard && navigator.clipboard.writeText){
          navigator.clipboard.writeText(p).then(function(){
            setStatus('已复制提示词到剪贴板：请在 WorkBuddy 粘贴发给小腾生成策略，再把返回的 JSON 贴回上方文本框', false);
          }, function(){
            setStatus('自动复制失败，请手动复制：<br><textarea readonly style="width:100%;height:110px">'+escapeHtml(p)+'</textarea>', false);
          });
        } else {
          setStatus('请复制并在 WorkBuddy 发给小腾：<br><textarea readonly style="width:100%;height:110px">'+escapeHtml(p)+'</textarea>', false);
        }
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
        if(navigator.clipboard && navigator.clipboard.writeText){
          navigator.clipboard.writeText(p).then(function(){
            setStatus('✅ 已复制基础信息：请在 WorkBuddy 粘贴发给小腾生成策略，再把返回的 JSON 贴回上方文本框', true);
          }, function(){
            setStatus('自动复制失败，请手动复制：<br><textarea readonly style="width:100%;height:120px">'+escapeHtml(p)+'</textarea>', false);
          });
        } else {
          setStatus('请复制并在 WorkBuddy 发给小腾：<br><textarea readonly style="width:100%;height:120px">'+escapeHtml(p)+'</textarea>', false);
        }
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
function aiCacheKey(obj){ return 'brief_aiparse_' + (obj||'').replace(/\\s+/g,' ').trim().toLowerCase(); }
function aiCacheGet(key){ try{ var v=sessionStorage.getItem(key); return v?JSON.parse(v):null; }catch(e){ return null; } }
function aiCacheSet(key,val){ try{ sessionStorage.setItem(key, JSON.stringify(val)); }catch(e){} }
function fillParse(j){
  setVal('goal_name', j.goal_name);
  setVal('start_date', j.start_date);
  setVal('end_date', j.end_date);
  setVal('overall_conv', j.overall_conv);
  setVal('is_revenue', j.is_revenue);
  setVal('budget', j.budget);
  setVal('locale', j.locale);
  setVal('audience_age', j.audience_age);
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


def build_strategy_prompt(brief: dict) -> str:
    """把 Brief 上下文拼成自包含提示词，交给 WorkBuddy（小腾）生成 StrategySpec JSON。"""
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
    tpl = (
        "你是营销 Agent 的 L1 策略合成角色。请基于以下 Brief 生成一份 StrategySpec JSON"
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
        "【画像包与内容侧重】\n"
        "1. 选画像包（GENERIC / HNW_FAMILY / YOUNG_TREND / PARENT_FAM / CORP_GRP / DORMANT）必须先在专家库查表（references/audience-content-map.json），按打分公式 score = Σ weight×match / Σ weight（阈值 0.6）匹配接触人字段。命中 ≥2 个时按分数降序列候选交运营选。\n"
        "2. 命中画像包后，频次 max_per_24h/max_per_7d、静默窗、触达时段、文案调性、画面调性、CTA 模板**必须**沿用该包 strategy；不允许凭感觉改写。\n"
        "3. 命中 0 个（且不为 GENERIC）：用 GENERIC 兜底。{multi_pkg}\n"
        "【国际化与落地页规则】\n"
        "1. 语言优先级由「国家/地区」和「语言/地区」共同决定：\n"
        "   · 若 audience_region 不包含「中国大陆」（仅港澳台/海外/未选），主语言强制为英文（en_US），忽略 zh_CN；\n"
        "   · 若 audience_region 包含「中国大陆」：\n"
        "     - locale 仅 zh_CN → 主内容中文；\n"
        "     - locale 仅 en_US → 主内容英文；\n"
        "     - locale 同时含 zh_CN 和 en_US → 主内容英文，附加中文翻译稿（可拆两个 campaign 或一个 campaign 内出 bilingual 变体）。\n"
        "2. 落地页 URL 按主语言区分，使用 Mautic 公开页路径 http://localhost:8080/s/<slug>：\n"
        "   · 中文主内容 → http://localhost:8080/s/<campaign-cid>-zh\n"
        "   · 英文主内容 → http://localhost:8080/s/<campaign-cid>-en\n"
        "3. 分群命名体现 region+locale，如 SEG_{goal_id}_CN_ZH、SEG_{goal_id}_GLOBAL_EN。\n"
        "【输出要求】\n"
        "1. 顶层：goal_id（slug）、objective、kpi（{{\"metric\":\"conversion\",\"target\":{oc_json}}}）、"
        "locale（[\"{locale}\"]）、audience_package（{aud_pkg}）、audience_profile（按目标人群特点字段填入）、"
        "campaigns（数组）、service_sequences（数组，可选）。\n"
        "2. 每个 campaign：{{\"cid\",\"name\",\"content_brief\":\"一句话说清这批人现在缺什么信息\","
        "\"content_emphasis\":[...画像包 strategy.levers...]，"
        "\"segment\":{{\"mode\":\"propose\",\"ref\":\"SEG_xxx\"}},"
        "\"send_conditions\":{{\"delay_hours\":int,\"max_per_24h\":int,\"max_per_7d\":int,"
        "\"quiet_hours\":\"22:00-09:00\"}},\"tags_to_write\":[...],\"email_mode\":\"reuse\"|\"generate\","
        "\"email_ref\":(reuse 填真实资产 alias/id，generate 填空),\"landing_page_url\":str,"
        "\"depends_on\":cid_or_null,\"editable_until_start\":bool,\"daily_adjust_window_hours\":24,"
        "\"content_variant\":int(可选),\"deferred\":bool(可选)}}\n"
        "3. 画像包命中后，第一个 campaign 的 depends_on 设为 null、editable_until_start=true；后续 campaign 串行（depends_on=前序 cid）、editable_until_start=false（等 c1 完成才由优化循环生成）。\n"
        "4. 分群必须按意图天然互斥（seed / broad / no-reach / host-confirm 等），不要共用同一 segment。\n"
        "5. 如需「用户动作即时触发」的确认件（非促销），放进 service_sequences 并设 quiet_hours_exempt=true + send_within_minutes<=5。\n"
        "6. 严格遵守约束/红线（免打扰、抑制名单、退订熔断 0.3% 等）。\n"
        "7. 只输出 JSON。\n"
    )
    return tpl.format(name=name, goal_id=goal_id, objective=objective,
                      start_date=start_date, end_date=end_date,
                      oc=oc, lang_label=lang_label, locale=locale, budget=budget,
                      is_revenue=str(is_revenue).lower(), cons=cons,
                      aud_pkg=aud_pkg, aud_block=aud_block, oc_json=oc_json,
                      multi_pkg=multi_pkg_txt)


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
    inferred = infer_audience_package(brief.get("audience_profile") or {})
    brief["audience_package"] = inferred.get("code", "GENERIC")
    brief["audience_packages"] = inferred.get("codes", [])
    brief["audience_match"] = inferred
    return build_strategy_prompt(brief)


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
                service_spec: list = None, prefill: dict = None) -> str:
    """
    运营只填「目标 + 约束」；分群/落库 tag/内容/频次等策略由 Agent 产出 StrategySpec。
    strategy_spec 非空时，右侧只读展示逐条策略摘要（供提交前确认）。
    prefill: 可选 dict（来自 /brief?goal_id=<id>），覆盖 ex 默认值。
             含 ref_goal_id 时，标题改为「改 Brief」+ 顶部 banner 提示。
    """
    ex = {"objective": "", "locale": "zh_CN", "budget": "0", "is_revenue": "0",
          "audience_age": "", "audience_gender": "", "audience_income": "",
          "audience_education": "", "audience_industry": "", "audience_source": "",
          "audience_region": "",
          "start_date": "2028-05-01", "end_date": "2028-07-09", "overall_conv": "",
          "goal_name": ""}
    if prefill:
        for k, v in prefill.items():
            if k in ex and v not in (None, ""):
                ex[k] = str(v)
    _is_prefill = bool(prefill and prefill.get("ref_goal_id"))
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
    age_buckets = ["", "18-24", "25-34", "35-44", "45-54", "55+"]
    gender_opts = ["", "男", "女", "未知"]
    income_opts = ["", "L1", "L2", "L3", "L4", "L5"]
    edu_opts = ["", "名校", "MBA", "211", "985", "QS100", "普通本科", "其他"]
    ind_opts = ["", "IT", "制造", "金融", "旅游", "教育", "医疗", "零售", "其他"]
    src_opts = ["", "CTL", "CSTS", "SPORT", "爬虫", "其他", "手动输入"]
    region_opts = ["", "中国大陆", "港澳台", "海外"]

    operator = (f"<div class='card'><h3>① 你的目标与约束（运营填写）</h3>"
                f"{fld('goal_name','营销/活动 内部简称（留空则用 ID 值；<span class=\"opt\">可选</span>）',ex['goal_name'])}"
                f"<label><span class='req'>*</span> 营销目标（必填，业务描述，至少 4 字符，非占位词）</label>"
                f"<textarea name='objective' rows='3' required placeholder='例：为「2027 元旦跨年演唱会」于 2026-12-20~2027-01-03 向 25-34 岁音乐爱好者推广门票，目标 5000 张转化；约束：每周≤3 封、晚 20:00 后不推送、含 9 折早鸟券'>{_esc(ex['objective'])}</textarea>"
                f"<p class='note'>示例：为「2027 元旦跨年演唱会」于 2026-12-20~2027-01-03 向 25-34 岁音乐爱好者推广门票，目标 5000 张转化；约束：每周≤3 封、晚 20:00 后不推送、含 9 折早鸟券。建议按「活动/主题 + 起止时间 + 目标人群 + 期望动作 + 数量目标 + 约束（频次上限 / 免打扰时段 / 是否含折扣）」描述；时间可写相对表达（如「万圣节前 3 个月」），AI 会自动推断具体日期。</p>"
                f"<button id='ai-parse-btn' class='btn sec' type='button' style='margin-top:8px'>✨ AI 识别意图（DeepSeek）</button>"
                f"<div id='ai-parse-status' class='note'></div>"
                f"<p class='note'>{('已配置 DeepSeek：点击将识别简称/日期/年龄/性别/收入/渠道来源等字段并回填上方表单；当活动周期 ≥7 天（或设了转化目标）时，还会自动合成多波次 StrategySpec。' if _deepseek_on else '未配置 DeepSeek：请在 config.json [deepseek].api_key 填入 key，或设置环境变量 DEEPSEEK_API_KEY。')}</p>"
                f"<div class='grid2'>"
                f"{fld('start_date','开始日期（<span class=\"opt\">可选</span>，留空用页面默认）',ex['start_date'])}"
                f"{fld('end_date','结束日期（<span class=\"opt\">可选</span>，留空用页面默认）',ex['end_date'])}</div>"
                f"<div class='grid2'>"
                f"{fld('overall_conv','项目预期转化率*跳转率（<span class=\"opt\">可选</span>，最终期望，0~1，如 0.15；留空=无要求走兜底逻辑）',ex['overall_conv'])}"
                f"</div>"

                # --- 目标人群特点（7 字段；画像包由系统推断） ---
                f"<div class='card-inner' style='background:#fafbf5;padding:12px;border-radius:8px;margin:8px 0'>"
                f"<h4 style='margin:6px 0'>目标人群特点</h4>"
                f"<p class='note'>填入受众字段后，系统按打分公式自动匹配画像包（家庭 / 年轻人 / 父母辈 / 公司客户 / 沉默客户激活）；无匹配则用 GENERIC 兜底。</p>"
                f"<div class='grid2'>"
                f"{_sel('audience_age','年龄段（多选）',ex['audience_age'],age_buckets,multiple=True)}"
                f"{_sel('audience_gender','性别（多选）',ex['audience_gender'],gender_opts,multiple=True)}</div>"
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
                f"<div style='margin-top:8px;display:flex;gap:8px;flex-wrap:wrap'>"
                f"<button id='gen-strategy-btn' class='btn sec' type='button'>✨ 自动生成策略</button>"
                f"<button id='copy-prompt-btn' class='btn ghost' type='button'>📋 复制基础信息（去 WorkBuddy 生成）</button>"
                f"</div>"
                f"<div id='gen-strategy-status' class='note'></div>"
                f"<p class='note'>{('已配置策略自动生成端点：点击将直接把 StrategySpec 填回上方文本框。' if _strategy_gen_on else ('已配置 DeepSeek：点击将直连 DeepSeek 自动生成 StrategySpec 并填回上方文本框。' if _deepseek_on else '未配置生成能力（无外部端点、无 DeepSeek）：点击后将把提示词复制到剪贴板，请在 WorkBuddy 粘贴发给小腾生成策略，再把返回的 JSON 贴回上方文本框。'))}</p>"
                f"<div id='plan-preview' class='note'>填写「总体目标转化率」与「开始 / 结束日期」后，将自动推算派生战役数量、单 campaign 点击率与合理性。</div>"
                f"<button class='btn' type='submit' style='margin-top:14px'>编译并生成 Program →</button>"
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
                f"      if(!ml) continue;  // 画像包未定义该字段 → 不计入分母"
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
                f"  var el=document.querySelector('[name=audience_'+k+']');"
                f"  if(el) el.addEventListener('change',_updateMatch);}});"
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
    _banner = (f"<p class='b-warn' style='margin:4px 0 12px'>📝 改 Brief 模式：已预填原 Program <code>{_esc(prefill.get('ref_goal_id',''))}</code> 的字段。"
               f"提交后将生成新的 Program（不会修改原 Program）。</p>") if _is_prefill else ""
    return (f"<div style='display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px'>"
            f"<h1 style='margin:0'>{_title}</h1>"
            f"<a class='btn sec' href='/' style='white-space:nowrap'>← 取消并返回列表</a>"
            f"</div>"
            f"<p class='sub'>方案 A 驾驶舱 · 独立 :8090 → Mautic :8080</p>" \
           f"{_banner}" \
           f"<form method='post' action='/brief'><div class='grid2'>{operator}{agent}</div></form>")


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


# 画像包 → 策略取向（只读展示；不随左侧受众字段切换）
_PERSONA_STRATEGY_ROWS = [
    ("家庭（HNW_FAMILY）",
     "以观赛家庭 / 亲子场景切入，CTA 主打「家庭优先购买资格」。沿用本地方案的种子验证→全量扩量骨架："
     "先用曾购票 / 高意向切片小批量验证（c1），通过后再扩全量（c2）；到过 LP 未提交者做一次异议回收（c3），"
     "始终未达 LP 者换标题 / 换角度复投一次（c4），host 官宣时借权威事件收口（c5）。登记即停促销、转服务确认。"),
    ("年轻人（YOUNG_TREND）",
     "走氛围与稀缺感角度（决赛唯一候选 / 优先资格），弱化条款、强化「第一时间拿到资格」。"
     "首波小批量验证后放量；c3 对到过 LP 未提交者降摩擦（表单减字段），c4 对零打开者换角度；同样 ≤3 触、免打扰与护栏约束。"),
    ("父母辈（PARENT_FAM）",
     "主打「带孩子看决赛」的价值主张与确定性信息（日期 / 场馆表述须按合规口径：host 待官宣前不得写成已确认）。"
     "按 5 波节奏执行；触达理由不足时不强行加波，宁用内容变体区分，避免频次堆叠。"),
    ("公司客户（CORP_GRP）",
     "以 Hospitality 包厢 / 企业观赛权益为主线，收入档 L4/L5。可纳入高意向种子切片直连 c1→c2；"
     "c5 借 host 确认事件做权威性收口，适合转客户经理跟进而非纯邮件触达。"),
    ("沉默客户激活（DORMANT）",
     "以外部权威事件（host 确认）或新权益作为重启理由，避免「纯提醒式」唤醒。"
     "归入差异化复投波（c4 / c5）；仍无互动者走抑制名单 / 清洗，不追加频次。"),
    ("GENERIC 通用兜底",
     "未命中任一画像包时走默认递进策略（分波递进：延迟递增、变体递增），"
     "发送受频次闸门 1/24h·3/7d、退订熔断 0.3% 与抑制名单护栏约束。"),
]


def _audience_plan_html() -> str:
    """② 区只读块：画像包 → 策略取向（内置文案映射）。"""
    head = "<h4 style='margin:12px 0 6px'>画像包 → 策略取向</h4>"
    rows = "".join(
        f"<div style='border-top:1px dashed #cfe3b7;padding:7px 0'>"
        f"<div><strong>{_esc(name)}</strong></div><div class='note'>{_esc(txt)}</div></div>"
        for name, txt in _PERSONA_STRATEGY_ROWS)
    return head + rows


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
                   f"fill='#1c2330' font-size='9'>{_esc(nd['id'].replace('wave_', 'campaign_') if isinstance(nd['id'], str) else nd['id'])}</text></g>")
    svg.append("</svg>")
    return "".join(svg)


def _mautic_asset_table(program: dict, idx: dict = None) -> str:
    """汇总 Program 内每个 campaign 引用/将新建的 Mautic 资产（新建 vs 调用已有）。
    若 idx 未传则自行读取一次 Mautic 资产索引；ref 在 Mautic 实存时渲染成可跳转详情页的外链。"""
    if idx is None:
        idx = _mautic_asset_index()
    avail = idx["available"]
    emails = idx["email"]; segs = idx["segment"]; pages = idx["page"]

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
                                  emails if kind == "email" else segs if kind == "分群" else pages) \
                else "✗"
        elif avail:
            real = "—"
        else:
            real = "未连"
        # 可解析为 Mautic 实体 → ref 变成外链
        ref_cell = f"<code>{_esc(ref)}</code>"
        lk_kind = {"email": "email", "分群": "segment", "着陆页": "landingpage"}.get(kind)
        if lk_kind and avail and ref not in ("（无）",):
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
        rows += _row("email", em_ref, em_mode)
        rows += _row("分群", seg, seg_mode)
        if lp:
            rows += _row("着陆页", lp, "reuse")
        else:
            rows += ("<tr><td>着陆页</td><td><code>—</code></td><td>generate</td>"
                     "<td>新建</td><td>未连</td></tr>" if not avail else
                     "<tr><td>着陆页</td><td><code>—</code></td><td>generate</td>"
                     "<td>新建</td><td>✗</td></tr>")
    note = ("（未连接 Mautic 或缺少凭证：以下为基于策略规格的预期清单，无外链）" if not avail
            else "（已连接 Mautic，✓=实存 / ✗=策略引用但 Mautic 中不存在；ref 可点击跳转详情页）")
    return (f"<div class='card'><h3>Mautic 资产清单（新建 vs 调用）</h3>"
            f"<p class='note'>{_esc(note)}</p>"
            f"<table><tr><th>类型</th><th>引用(ref)</th><th>模式</th>"
            f"<th>结论</th><th>实存</th></tr>{rows}</table></div>")


# --------------------------- Mautic 外链（资产已在 :8080/s/ 生成 → 跳转详情页） ---------------------------
_MAUTIC_ADMIN_ROUTES = {
    "campaign": "/s/campaigns/{id}",
    "email": "/s/emails/{id}/view",
    "segment": "/s/segments/{id}",
    "landingpage": "/s/landingpages/{id}",
    "sms": "/s/sms/{id}/view",
}

def _mautic_base() -> str:
    """Mautic 实例 base URL（来自 config.json 的 local.base_url）。"""
    try:
        return load_config("local").get("base_url", "http://localhost:8080").rstrip("/")
    except Exception:  # noqa: BLE001
        return "http://localhost:8080"

def _mautic_asset_index() -> dict:
    """读取 Mautic 已存在资产，构建 ref→id 索引（email/segment/landingpage）。
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
    }

def _mautic_ext_link(kind: str, ref, idx: dict) -> str:
    """返回 Mautic 详情页外链 <a>；不可解析（未连接/未找到/未知类型）返回空串。
    kind: campaign | email | segment | landingpage。"""
    base = _mautic_base()
    routes = _MAUTIC_ADMIN_ROUTES
    if kind == "campaign":
        if not ref:
            return ""
        return (f"<a class='ext' href='{base}{routes['campaign'].format(id=ref)}' "
                f"target='_blank' rel='noopener'>Mautic 战役详情</a>")
    if kind in ("email", "segment", "landingpage"):
        if not idx or not idx.get("available"):
            return ""
        key = "page" if kind == "landingpage" else kind
        mid = idx.get(key, {}).get(str(ref) if ref else "")
        if not mid:
            return ""
        return (f"<a class='ext' href='{base}{routes[kind].format(id=mid)}' "
                f"target='_blank' rel='noopener'>详情</a>")
    return ""


def _mautic_campaign_name(campaign_id) -> str:
    """返回 Mautic campaign 的实时名字（单个 GET、不缓存，保证改名后同步到 Program 页）；
    失败回退列表缓存；再失败返回空串。"""
    if not campaign_id:
        return ""
    nm = (mautic_get_campaign(campaign_id).get("name") or "").strip()
    if not nm:
        nm = mautic_read_campaigns("local").get("by_id", {}).get(str(campaign_id), "")
    return nm


def _program_body(program: dict, msg: str = "") -> str:
    gid = program["goal_id"]
    goal = program["goal"]
    # 自适应规则说明
    rules = ("<p class='note'>自适应规则（确定性，可审计）：上游完成后按「达成率/退订率」改写下游 —— "
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
        plan_html = (f"<div class='card'><h3>派生计划摘要（系统反推，无需手填）</h3>"
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
        # 方案优化预览（_optimize_preview，只读预判；「采纳并应用」才真正回写下游）
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
                            f"<button class='btn sm' type='submit'>采纳并应用（回写下游）</button></form>")
        complete_f = (f"<form method='post' action='/program/{gid}/complete' style='margin-top:8px'>"
                      f"<input type='hidden' name='cid' value='{_esc(c['cid'])}'>"
                      f"<input name='conversion' placeholder='达成率0~1（留空用回填）' style='width:150px;display:inline-block'>"
                      f"<input name='unsub' placeholder='退订率0~1' style='width:120px;display:inline-block'>"
                      f"<button class='btn sm ghost' type='submit'>标记完成并回写达成 → 改写下游</button></form>")
        result_txt = ""
        if c.get("result"):
            result_txt = (f"<span class='pill'>达成 {c['result'].get('conversion')} · "
                          f"退订 {c['result'].get('unsub')}</span>")
        # Mautic 外链（资产已在 :8080/s/ 生成才给链接；campaign 需已推送拿到 id）
        dr = c["proposal"].get("deploy_result") or {}
        # campaign 名字：未生成（无 Mautic id）→ 内部 cid；已生成 → Mautic 实时名字（可点跳详情页，改名后同步）
        mcid = dr.get("campaign_id") if not dr.get("dry_run") else None
        if mcid:
            _mname = _mautic_campaign_name(mcid) or f"campaign #{mcid}"
            cname_html = (f"<a class='ext' href='{_mautic_base()}/s/campaigns/{_esc(str(mcid))}' "
                          f"target='_blank' rel='noopener' title='Mautic campaign #{_esc(str(mcid))}'>{_esc(_mname)}</a>")
        else:
            cname_html = f"<code>{_esc(c['cid'])}</code>"
        ext_bits = []
        _em_ref = c["strategy"].get("email_ref", "")
        _seg_ref = c["strategy"].get("segment", "")
        _lp_ref = c["strategy"].get("landing_page_ref", "")
        _lp_url = c["strategy"].get("landing_page_url", "")
        if _em_ref:
            _lk = _mautic_ext_link("email", _em_ref, idx)
            ext_bits.append(f"邮件 {_lk if _lk else '<span class=note>（Mautic 无对应，无外链）</span>'}")
        if _seg_ref:
            _lk = _mautic_ext_link("segment", _seg_ref, idx)
            ext_bits.append(f"分群 {_lk if _lk else '<span class=note>（Mautic 无对应，无外链）</span>'}")
        if _lp_ref or _lp_url:
            _lk = _mautic_ext_link("landingpage", _lp_ref, idx) if _lp_ref else ""
            if _lk:
                ext_bits.append(f"落页 {_lk}")
            elif _lp_url:
                ext_bits.append(f"落页 <a class='ext' href='{_esc(_lp_url)}' target='_blank' rel='noopener'>详情</a>")
        ext_html = ("<p class='pill'>Mautic 外链：" + " · ".join(ext_bits) + "</p>") if ext_bits else ""
        cards += (f"<div class='card'><div style='display:flex;justify-content:space-between;align-items:center'>"
                  f"<strong>{_esc(c['wave_id'].replace('wave_', 'campaign_') if isinstance(c['wave_id'], str) else c['wave_id'])} · {cname_html}</strong>{st_badge}</div>"
                  f"<p style='margin:8px 0'>{_strategy_summary(c['strategy'])}</p>"
                  f"<p class='pill'>plan_hash <code>{_esc(prop['plan_hash'][:14])}</code> · 审批 {ap_txt} {result_txt}</p>"
                  f"{goals_txt}{fb_txt}{ext_html}"
                  f"<details><summary class='pill'>事件图（{len(prop['graph'])} 节点 · 流程图）</summary>"
                  f"{_graph_svg(prop['graph'])}</details>"
                  f"{defer_note}{qh_c}{approve_f}{push_f}{create_f}{defer_f}{goals_f}{feedback_f}"
                  f"{optimize_btn}{fa_html}{opt_html}{complete_f}</div>")
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
                   f"</p>"
                   f"<h1>Program {_esc(gid)}</h1>"
                   f"<p class='sub'>目标名称：{_esc(goal_name) if goal_name else '（未命名）'} "
                   f"（ID: {_esc(gid)}）<br>"
                   f"{_esc(goal.get('objective',''))} · 渠道 {_esc(','.join(goal.get('channels',[])))}"
                   f" · {program['n_campaigns']} 个 campaign"
                   f"{(' + ' + str(program.get('n_service_sequences', 0)) + ' 条服务序列') if program.get('n_service_sequences') else ''}"
                   f" · 策略来源 {src_html}</p>")
    return (f"{msg}{header_html}"
            f"{plan_html}{kpi_html}{cons_html}<div class='card'>{rules}</div>{cards}{svc}{report_html}{clog}")


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

    def _send_json(self, obj: dict):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", ""):
            return self._send(200, _page("驾驶舱", _dash_body()))
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
            return self._handle_brief(jsbody)
        if path == "/brief/generate-strategy":
            return self._handle_generate_strategy(jsbody)
        if path == "/brief/ai-parse":
            return self._handle_ai_parse(jsbody)
        if path == "/brief/strategy-prompt":
            return self._handle_strategy_prompt(jsbody)
        if path.endswith("/approve") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._handle_campaign_approve(gid, cid, jsbody)
        if path.endswith("/push") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._handle_campaign_push(gid, cid)
        if path.endswith("/activate") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._handle_campaign_activate(gid, cid)
        if path.endswith("/goals") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._handle_campaign_goals(gid, cid, jsbody)
        if path.endswith("/create") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._handle_campaign_create(gid, cid)
        if path.endswith("/auto-feedback"):
            gid = path.split("/")[2] if path.startswith("/program/") else ""
            qs = dict(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            date_str = (qs.get("date") or [_yesterday_str()])[0]
            return self._handle_program_auto_feedback(gid, date_str)
        if path.endswith("/feedback") and "/campaign/" in path:
            gid, cid = self._split_campaign(path)
            return self._handle_campaign_feedback(gid, cid, jsbody)
        if path.endswith("/complete"):
            return self._handle_complete(jsbody)
        if path.endswith("/approve") and "/service/" in path:
            parts = [x for x in path.split("/") if x]
            return self._handle_service_approve(parts[1], parts[3], jsbody)
        if path.endswith("/push") and "/service/" in path:
            parts = [x for x in path.split("/") if x]
            return self._handle_service_push(parts[1], parts[3])
        if path.endswith("/approve"):
            gid = path.split("/")[-2]
            return self._handle_legacy_approve(gid, jsbody)
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
                locales = d.get("locales") or ["zh_CN"]
            if not locales:
                locales = ["zh_CN"]
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
            _save_program(program)
            self.send_response(302)
            self.send_header("Location", f"/program/{goal.goal_id}")
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
                "你是营销 Agent 的 L1 策略合成器。只输出严格 JSON，不要解释文字、"
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
            "- audience_age: 枚举字符串或多值（多个值用英文逗号分隔，不要空格，如 \"18-24,25-34\"）。"
            "可取值：\"\" / \"18-24\" / \"25-34\" / \"35-44\" / \"45-54\" / \"55+\"。"
            "把年龄描述映射到覆盖该范围的所有档位：\n"
            "  · \"18~34 岁\"、\"18-34 岁\"、\"18 到 34 岁\" → \"18-24,25-34\"；\n"
            "  · \"18-30\" → \"18-24,25-34\"；\"30-40\" → \"35-44\"；\"40-50\" → \"45-54\"；\n"
            "  · \"40 岁以下\"、\"35 岁及以下\" → \"18-24,25-34\"（若强调「20 出头」「年轻」则 \"18-24\"）；\n"
            "  · \"50 岁以上\"、\"60 岁以上\" → \"55+\"；\"中年\"、\"35 岁以上\" → \"35-44,45-54\"。未提及年龄则 \"\"。\n"
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
                  "budget", "locale", "audience_age", "audience_gender",
                  "audience_income", "audience_source", "audience_education",
                  "audience_industry", "audience_region", "constraints", "strategy_spec")
        # 中文标签（前端 filled 提示用）
        field_label = {
            "goal_name": "活动简称", "start_date": "开始日期", "end_date": "结束日期",
            "overall_conv": "转化率", "is_revenue": "是否营收", "budget": "预算", "locale": "语言",
            "audience_age": "年龄", "audience_gender": "性别", "audience_income": "收入",
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
            if v:
                filled.append(field_label.get(f, f))

        # 方案 B：意图识别未直接产出 strategy_spec 时，按启发式自动合成多波策略
        strategy_auto = False
        if not out.get("strategy_spec") and _should_synthesize_strategy(out):
            try:
                from goal_intake import infer_audience_package
                brief = _brief_from_parsed(out, objective)
                inferred = infer_audience_package(brief.get("audience_profile") or {})
                brief["audience_package"] = inferred.get("code", "GENERIC")
                brief["audience_packages"] = inferred.get("codes", [])
                brief["audience_match"] = inferred
                prompt = build_strategy_prompt(brief)
                content = _deepseek_completion(
                    "你是营销 Agent 的 L1 策略合成器。只输出严格 JSON，不要解释文字、"
                    "不要 markdown 代码块，只输出可被 json.loads 解析的 StrategySpec 对象。",
                    prompt)
                spec = _extract_strategy_spec(content)
                if spec:
                    out["strategy_spec"] = spec
                    strategy_auto = True
            except RuntimeError:
                pass  # 合成失败不阻断字段回填（前端仍拿到识别字段）
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
              「采纳并应用」按钮 POST /complete（带 conv/unsub）才真正回写下游。
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
        # 分支维度（第 3 轴）：新增折扣挽回分支 / 剪掉挂起兜底分支
        branch_lines = []
        for nb in out.get("new_campaigns", []):
            branch_lines.append(f"➕ 新增修正分支 <b>{_esc(nb['cid'])}</b>（折扣挽回，覆盖未转化联系人）")
        for pr in out.get("pruned_campaigns", []):
            branch_lines.append(f"✂️ 剪掉挂起分支 <b>{_esc(pr['cid'])}</b>（已达标，不再需要）")
        branch_txt = ("<br>" + "<br>".join(branch_lines)) if branch_lines else ""
        verdict_lbl = out.get("verdict")
        msg = (f"<div class='card'><p class='b-ok'>上游 {_esc(cid)} 完成（{_esc(done_lbl)}），"
               f"判定 <b>{_esc(verdict_lbl or '—')}</b>，达成率 {_esc(ratio_txt)}<br>"
               f"下游改写：{_esc(changed)}{branch_txt}</p></div>")
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
