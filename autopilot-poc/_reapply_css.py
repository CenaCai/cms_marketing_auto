import io

P = r'C:/Users/cenacai/WorkBuddy/2026-08-31-18-52-03/autopilot-poc/cockpit.py'

NEW_CSS = r''':root{
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
.header .logo{font-size:18px;font-weight:600;letter-spacing:.4px}
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
.btn:hover{background:var(--brand-2);box-shadow:0 4px 12px rgba(37,99,235,.32)}
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
'''

with io.open(P, 'r', encoding='utf-8') as f:
    src = f.read()

marker = 'CSS = """'
assert marker in src, "CSS marker not found"
start = src.index(marker) + len(marker)
end = src.index('"""', start)
new_src = src[:start] + NEW_CSS + src[end:]

with io.open(P, 'w', encoding='utf-8', newline='\n') as f:
    f.write(new_src)

print("REAPPLIED_OK old_len=%d new_block_len=%d" % (end - start, len(NEW_CSS)))
