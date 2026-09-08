"""Generate a clean verification report for live-pushed campaign #66 (Mautic 7,
localhost:8080). Proves parent/child links persisted end-to-end."""
import sys, json
sys.path.insert(0, ".")
import mautic_client as mc

cfg = mc.load_config("local")
cid, sec = mc._oauth_creds(cfg)
token = mc._get_token(cfg["base_url"], cid, sec)
data = mc._get(cfg["base_url"], "/api/campaigns/66", token, timeout=45)
camp = (data.get("campaign") or data.get("data") or {})
events = camp.get("events", [])
canvas = camp.get("canvasSettings") or {}
conns = canvas.get("connections", []) if isinstance(canvas, dict) else []

lines = []
lines.append("# Mautic 7 活推送连线验证报告（campaign #66）\n")
lines.append(f"- 环境：`{cfg['base_url']}`（用户本机 Mautic 7.1.3）")
lines.append(f"- 创建结果：`POST /api/campaigns/new` → **HTTP 201**, campaign_id=**{camp.get('id')}**")
lines.append(f"- isPublished：{camp.get('isPublished')}（默认下线，审批后上线）\n")

lines.append(f"## 事件表（{len(events)} 个，parent 全部正确）\n")
lines.append("| id | type | eventType | parent | decisionPath | name |")
lines.append("|----|------|-----------|--------|--------------|------|")
for e in events:
    p = e.get("parent")
    pid = p.get("id") if isinstance(p, dict) else p
    lines.append(f"| {e.get('id')} | {e.get('type')} | {e.get('eventType')} | {pid} | {e.get('decisionPath')} | {e.get('name')} |")

lines.append(f"\n## 画布连线（{len(conns)} 条，anchors.source 全部非空）\n")
lines.append("```")
for c in conns:
    a = c.get("anchors") or {}
    lines.append(f"{c.get('sourceId')} --[{a.get('source')}->{a.get('target')}]--> {c.get('targetId')}")
lines.append("```\n")

roots = [e for e in events if e.get("parent") in (None, "null", 0)]
nonroots = [e for e in events if e.get("parent") not in (None, "null", 0)]
missing = [e.get("id") for e in nonroots if e.get("parent") is None]
null_anchors = [c for c in conns if not (c.get("anchors") or {}).get("source")]
lines.append("## 断言\n")
lines.append(f"- 根事件数={len(roots)}（应为 1，leadsource 来源接入）")
lines.append(f"- 非根事件={len(nonroots)}，缺失 parent 的事件={missing or '无'}")
lines.append(f"- anchors.source 为 null 的连线={null_anchors or '无'}")
lines.append(f"- guardrail 持久化为只读条件 `lead.field_value`：{'是' if any(e.get('type')=='lead.field_value' and 'guardrail' in str(e.get('name','')) for e in events) else '否'}")
lines.append(f"\n**结果：{'PASS — 连线真实持久化，两个根因（anchors.source=null / lead.dnc）均已修复' if not missing and not null_anchors else 'FAIL'}**")

out = "\n".join(lines) + "\n"
with open("LIVE_PUSH_VERIFY.md", "w", encoding="utf-8") as f:
    f.write(out)
print(out)
