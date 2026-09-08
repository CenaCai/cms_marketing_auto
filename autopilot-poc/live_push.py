import json
import urllib.request
import mautic_client as m
import goal_intake
import plan_compiler

cfg = m.load_config("local")
base = cfg["base_url"]
cid, sec = m._oauth_creds(cfg)
tok = m._get_token(base, cid, sec)


def getj(path):
    req = urllib.request.Request(base + path, method="GET")
    req.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# 取真实 segment / email 作来源与事件引用
segs = getj("/api/segments")
sc = segs.get("segments", segs.get("lists", segs))
seg_items = list(sc.values()) if isinstance(sc, dict) else (sc if isinstance(sc, list) else [])
seg_id = seg_items[0].get("id") if seg_items else None
print("using segment_id =", seg_id)

emails = getj("/api/emails")
ec = emails.get("emails", emails.get("lists", emails))
email_items = list(ec.values()) if isinstance(ec, dict) else (ec if isinstance(ec, list) else [])
email_id = email_items[0].get("id") if email_items else None
print("using email_id =", email_id)

brief = {
    "objective": "OAuth2 活推送连线验证测试 2026",
    "goal_name": "oauth_live_test",
    "overall_conv": 0.15,
    "start_date": "2028-05-01",
    "end_date": "2028-07-09",
    "is_revenue": False,
    "locale": "zh_CN",
}
goal = goal_intake.parse_brief(brief)

strategy = {
    "cid": "oauth_live_test",
    "intent": "promo",
    "segment_id": seg_id,
    "segment": f"SEG_{seg_id}",
    "segment_ref": f"SEG_{seg_id}",
    "segment_mode": "reuse",
    "email_ref": email_id,
    "email_mode": "reuse",
    "subject": "OAuth2 活推送连线验证",
    "wave_id": "wave_1",
    "tags_to_write": ["oauth_live_test"],
    "landing_page_url": "http://localhost:8080/s/ucl2028-bridge",
    "send_conditions": {"delay_hours": 24},
}

proposal = plan_compiler.compile(goal, strategy)
print("mautic_events count =", len(proposal.get("mautic_events", [])))
print("mautic_canvas nodes =", len(proposal.get("mautic_canvas", {}).get("nodes", [])))
print("mautic_canvas connections =", len(proposal.get("mautic_canvas", {}).get("connections", [])))
print("mautic_lists =", proposal.get("mautic_lists"))

result = m.push(proposal, "local", approved=False)
print("\n=== PUSH RESULT ===")
print(json.dumps(result, ensure_ascii=False, indent=2))

# 回读创建的 campaign，验证 events / parent / connections 真落库
new_id = result.get("campaign_id")
if new_id:
    got = getj(f"/api/campaigns/{new_id}")
    camp = got.get("campaign", got)
    evs = camp.get("events", [])
    print("\n=== READBACK campaign", new_id, "===")
    print("name =", camp.get("name"), "| isPublished =", camp.get("isPublished"))
    print("events returned =", len(evs) if isinstance(evs, list) else evs)
    if isinstance(evs, list):
        for e in evs[:6]:
            print(f"  - id={e.get('id')} type={e.get('type')} parent={e.get('parent')} name={e.get('name')}")
    # canvasSettings connections
    cs = camp.get("canvasSettings") or camp.get("canvasSettingsRaw") or {}
    print("canvasSettings keys =", list(cs.keys()) if isinstance(cs, dict) else cs)
