import sys

P = r'C:/Users/cenacai/WorkBuddy/2026-08-31-18-52-03/autopilot-poc/cockpit.py'
with open(P, 'r', encoding='utf-8') as f:
    content = f.read()

PATCHES = []

# S1: imports
PATCHES.append(('imports',
'''import argparse
import html
import json
import os
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer''',
'''import argparse
import html
import json
import os
import time
import traceback
import urllib.parse
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer'''))

# S2: COCKPIT_LOG buffer + helper
PATCHES.append(('buffer',
'''HERE = os.path.dirname(os.path.abspath(__file__))''',
'''HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------- 开发日志（仅本地驾驶舱可见） ---------------------------
COCKPIT_LOG = deque(maxlen=200)


def cockpit_log(level: str, msg: str) -> None:
    """记录一条开发日志（INFO / WARN / ERROR / OK）。level 用于面板配色。"""
    ts = time.strftime("%H:%M:%S")
    COCKPIT_LOG.append((ts, level, msg))'''))

# P1: CSS devlog panel
PATCHES.append(('css-devlog',
'''.pill{font-size:11px;color:var(--muted)}
"""''',
'''.pill{font-size:11px;color:var(--muted)}
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
"""'''))

# P2: _page + _dev_log_panel
PATCHES.append(('page-panel',
'''def _page(title: str, body: str) -> str:
    return PAGE.format(title=_esc(title), css=CSS, body=body)''',
'''def _page(title: str, body: str) -> str:
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
            f"<div class='dl-box'>{''.join(rows)}</div></details>")'''))

# S5: _guard method
PATCHES.append(('guard-method',
'''    def log_message(self, *a):
        pass''',
'''    def log_message(self, *a):
        pass

    def _guard(self, label, fn, *args, **kwargs):
        """包裹写操作：未捕获异常记入开发日志并渲染带日志面板的 500 页。"""
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            cockpit_log("ERROR", f"{label} 未捕获异常:\\n{tb}")
            try:
                self._send(500, _page(
                    f"500 · {label}",
                    f"<div class='card'><p class='b-bad'>处理「{_esc(label)}」时抛出未捕获异常：</p>"
                    f"<pre class='pre'>{_esc(tb)}</pre>"
                    f"<p class='note'>完整上下文见页面底部「开发日志」面板。</p></div>"))
            except Exception:  # noqa: BLE001
                pass
            return None'''))

# P3: brief instrumentation
PATCHES.append(('brief-log',
'''            try:
                _resolve_program_project(program, "local")
            except Exception:  # noqa: BLE001
                pass
            _save_program(program)''',
'''            try:
                _resolve_program_project(program, "local")
            except Exception as _pe:  # noqa: BLE001
                cockpit_log("WARN", f"brief 建 Mautic project 失败（降级 None，推送时惰性补建）：{type(_pe).__name__}: {_pe}")
            _save_program(program)
            cockpit_log("OK", f"brief 已生成 Program：goal_id={program.get('goal_id')} · mautic_project_id={program.get('mautic_project_id')} · campaigns={len(program.get('campaigns', []))}")'''))

# P4: complete instrumentation
PATCHES.append(('complete-log',
'''        out = evaluate_and_replan(p, cid, result)
        if "error" in out:
            msg = f"<div class='card'><p class='b-bad'>{_esc(out['error'])}</p></div>"
            return self._send(200, _page("Program", _program_body(p, msg)))
        _save_program(p)''',
'''        cockpit_log("INFO", f"complete {cid}：evaluate_and_replan 开始（conv={result['conversion']}, unsub={result['unsub']}）")
        out = evaluate_and_replan(p, cid, result)
        if "error" in out:
            cockpit_log("ERROR", f"complete {cid} 失败：{out['error']}")
            msg = f"<div class='card'><p class='b-bad'>{_esc(out['error'])}</p></div>"
            return self._send(200, _page("Program", _program_body(p, msg)))
        _save_program(p)
        cockpit_log("OK", f"complete {cid}：verdict={out.get('verdict')} · changes={len(out.get('changes', []))} · new={len(out.get('new_campaigns', []))} · pruned={len(out.get('pruned_campaigns', []))}")'''))

# P5: service_push INFO
PATCHES.append(('service-info',
'''        ok, reason = verify_push(s["proposal"], s["proposal"].get("approval"))''',
'''        cockpit_log("INFO", f"service_push {sid}：开始（program={gid}，已审批校验）")
        ok, reason = verify_push(s["proposal"], s["proposal"].get("approval"))'''))

# P6: service_push OK
PATCHES.append(('service-ok',
'''            _save_program(p)
            msg = (f"<div class='card'><p class='b-ok'>服务序列已提交推送"''',
'''            _save_program(p)
            cockpit_log("OK", f"service_push {sid}：推送成功（{'dry-run' if result.get('dry_run') else result.get('env')}）")
            msg = (f"<div class='card'><p class='b-ok'>服务序列已提交推送"'''))

# P7: service_push ERROR
PATCHES.append(('service-err',
'''            msg = (f"<div class='card'><p class='b-bad'>服务序列推送失败（已回滚 deployed）：{_esc(push_err)}</p>"''',
'''            cockpit_log("ERROR", f"service_push {sid}：推送失败 {push_err}")
            msg = (f"<div class='card'><p class='b-bad'>服务序列推送失败（已回滚 deployed）：{_esc(push_err)}</p>"'''))

# P8: campaign_push INFO
PATCHES.append(('campaign-info',
'''        ok, reason = verify_push(c["proposal"], c["proposal"].get("approval"))''',
'''        cockpit_log("INFO", f"campaign_push {cid}：开始（program={gid}，已审批校验）")
        ok, reason = verify_push(c["proposal"], c["proposal"].get("approval"))'''))

# P9: campaign_push OK
PATCHES.append(('campaign-ok',
'''            note = "dry-run" if result.get("dry_run") else result.get("env")
            msg = f"<div class='card'><p class='b-ok'>已提交推送（{_esc(note)}）：{_esc(reason or '已上线')}</p></div>"''',
'''            note = "dry-run" if result.get("dry_run") else result.get("env")
            cockpit_log("OK", f"campaign_push {cid}：推送成功（{note}）")
            msg = f"<div class='card'><p class='b-ok'>已提交推送（{_esc(note)}）：{_esc(reason or '已上线')}</p></div>"'''))

# P10: campaign_push ERROR
PATCHES.append(('campaign-err',
'''            msg = (f"<div class='card'><p class='b-bad'>推送失败（已回滚 status）：{_esc(push_err)}</p>"''',
'''            cockpit_log("ERROR", f"campaign_push {cid}：推送失败 {push_err}")
            msg = (f"<div class='card'><p class='b-bad'>推送失败（已回滚 status）：{_esc(push_err)}</p>"'''))

# P11: legacy_push INFO
PATCHES.append(('legacy-info',
'''        ok, reason = verify_push(d, d.get("approval"))''',
'''        cockpit_log("INFO", f"legacy_push {gid}：开始（提案校验）")
        ok, reason = verify_push(d, d.get("approval"))'''))

# P12: legacy_push OK
PATCHES.append(('legacy-ok',
'''        msg = f"<div class='card'><p class='b-ok'>已提交推送（{_esc('dry-run' if result.get('dry_run') else result.get('env'))}）：{_esc(reason)}</p></div>"''',
'''        cockpit_log("OK", f"legacy_push {gid}：推送成功（{'dry-run' if result.get('dry_run') else result.get('env')}）")
        msg = f"<div class='card'><p class='b-ok'>已提交推送（{_esc('dry-run' if result.get('dry_run') else result.get('env'))}）：{_esc(reason)}</p></div>"'''))

# P13: campaign_create INFO
PATCHES.append(('create-info',
'''        # 推之前先记 approved_idle（避免直接跳 executing 之后再被回滚显得反复）
        c["status"] = "approved_idle"
        _save_program(p)''',
'''        # 推之前先记 approved_idle（避免直接跳 executing 之后再被回滚显得反复）
        cockpit_log("INFO", f"campaign_create {cid}：开始创建并推送（program={gid}）")
        c["status"] = "approved_idle"
        _save_program(p)'''))

# P14: campaign_create OK
PATCHES.append(('create-ok',
'''            msg = (f"<div class='card'><p class='b-ok'>✅ {_esc(cid)} 已真实推送到 Mautic"''',
'''            cockpit_log("OK", f"campaign_create {cid}：已真实推送（campaign_id={result.get('campaign_id')}）")
            msg = (f"<div class='card'><p class='b-ok'>✅ {_esc(cid)} 已真实推送到 Mautic"'''))

# P15: campaign_create WARN
PATCHES.append(('create-warn',
'''            msg = (f"<div class='card'><p class='b-warn'>⚠️ {_esc(cid)} 仅 dry-run（未真正创建 campaign）：{_esc(note)}</p>"''',
'''            cockpit_log("WARN", f"campaign_create {cid}：仅 dry-run（{note}）")
            msg = (f"<div class='card'><p class='b-warn'>⚠️ {_esc(cid)} 仅 dry-run（未真正创建 campaign）：{_esc(note)}</p>"'''))

# P16: campaign_create ERROR
PATCHES.append(('create-err',
'''            msg = (f"<div class='card'><p class='b-bad'>❌ {_esc(cid)} 推送失败{mcid_txt}：{_esc(push_err)}</p>"''',
'''            cockpit_log("ERROR", f"campaign_create {cid}：推送失败{mcid_txt}：{push_err}")
            msg = (f"<div class='card'><p class='b-bad'>❌ {_esc(cid)} 推送失败{mcid_txt}：{_esc(push_err)}</p>"'''))

# P17: do_GET request log
PATCHES.append(('get-log',
'''        path = urllib.parse.unquote(self.path.split("?")[0])
        if path in ("/", ""):''',
'''        path = urllib.parse.unquote(self.path.split("?")[0])
        cockpit_log("INFO", f"GET {path}")
        if path in ("/", ""):'''))

# P18: do_POST request log
PATCHES.append(('post-log',
'''        path = urllib.parse.unquote(self.path.split("?")[0])
        length = int(self.headers.get("Content-Length", 0))''',
'''        path = urllib.parse.unquote(self.path.split("?")[0])
        cockpit_log("INFO", f"POST {path}")
        length = int(self.headers.get("Content-Length", 0))'''))

# P19: dispatch wraps
WRAPS = [
    ('brief', '        return self._handle_brief(jsbody)', '        return self._guard("brief", self._handle_brief, jsbody)'),
    ('generate-strategy', '        return self._handle_generate_strategy(jsbody)', '        return self._guard("generate-strategy", self._handle_generate_strategy, jsbody)'),
    ('ai-parse', '        return self._handle_ai_parse(jsbody)', '        return self._guard("ai-parse", self._handle_ai_parse, jsbody)'),
    ('strategy-prompt', '        return self._handle_strategy_prompt(jsbody)', '        return self._guard("strategy-prompt", self._handle_strategy_prompt, jsbody)'),
    ('campaign-approve', '            return self._handle_campaign_approve(gid, cid, jsbody)', '            return self._guard("campaign-approve", self._handle_campaign_approve, gid, cid, jsbody)'),
    ('campaign-push', '            return self._handle_campaign_push(gid, cid)', '            return self._guard("campaign-push", self._handle_campaign_push, gid, cid)'),
    ('campaign-activate', '            return self._handle_campaign_activate(gid, cid)', '            return self._guard("campaign-activate", self._handle_campaign_activate, gid, cid)'),
    ('campaign-goals', '            return self._handle_campaign_goals(gid, cid, jsbody)', '            return self._guard("campaign-goals", self._handle_campaign_goals, gid, cid, jsbody)'),
    ('campaign-create', '            return self._handle_campaign_create(gid, cid)', '            return self._guard("campaign-create", self._handle_campaign_create, gid, cid)'),
    ('program-auto-feedback', '            return self._handle_program_auto_feedback(gid, date_str)', '            return self._guard("program-auto-feedback", self._handle_program_auto_feedback, gid, date_str)'),
    ('program-delete', '            return self._handle_program_delete(gid)', '            return self._guard("program-delete", self._handle_program_delete, gid)'),
    ('campaign-feedback', '            return self._handle_campaign_feedback(gid, cid, jsbody)', '            return self._guard("campaign-feedback", self._handle_campaign_feedback, gid, cid, jsbody)'),
    ('complete', '            return self._handle_complete(jsbody)', '            return self._guard("complete", self._handle_complete, jsbody)'),
    ('replan-prompt', '                return self._handle_replan_prompt(_parts[1], _parts[3], jsbody)', '                return self._guard("replan-prompt", self._handle_replan_prompt, _parts[1], _parts[3], jsbody)'),
    ('confirm-strategy', '        return self._handle_confirm_strategy(jsbody)', '        return self._guard("confirm-strategy", self._handle_confirm_strategy, jsbody)'),
    ('service-approve', '            return self._handle_service_approve(parts[1], parts[3], jsbody)', '            return self._guard("service-approve", self._handle_service_approve, parts[1], parts[3], jsbody)'),
    ('service-push', '            return self._handle_service_push(parts[1], parts[3])', '            return self._guard("service-push", self._handle_service_push, parts[1], parts[3])'),
    ('legacy-approve', '            return self._handle_legacy_approve(gid, jsbody)', '            return self._guard("legacy-approve", self._handle_legacy_approve, gid, jsbody)'),
    ('legacy-push', '            return self._handle_legacy_push(gid)', '            return self._guard("legacy-push", self._handle_legacy_push, gid)'),
    ('dashboard', '            return self._send(200, _page("驾驶舱", _dash_body()))', '            return self._guard("dashboard", lambda: self._send(200, _page("驾驶舱", _dash_body())))'),
    ('program-view', '            return self._send(200, _page("Program", _program_body(p)))', '            return self._guard("program-view", lambda: self._send(200, _page("Program", _program_body(p))))'),
    ('proposal-view', '            return self._send(200, _page("提案", _proposal_body(d)))', '            return self._guard("proposal-view", lambda: self._send(200, _page("提案", _proposal_body(d))))'),
]
for label, old, new in WRAPS:
    PATCHES.append(('wrap-' + label, old, new))

applied, skipped, missing = [], [], []
for label, old, new in PATCHES:
    if new in content:
        skipped.append(label)
    elif old in content:
        content = content.replace(old, new, 1)
        applied.append(label)
    else:
        missing.append(label)

with open(P, 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)

print("APPLIED:", len(applied))
for x in applied:
    print("  +", x)
print("SKIPPED:", len(skipped))
for x in skipped:
    print("  =", x)
print("MISSING:", len(missing))
for x in missing:
    print("  !", x)
