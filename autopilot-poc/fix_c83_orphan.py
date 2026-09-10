"""修复 Mautic campaign 83 的孤儿事件并发布。

诊断：lists(segment 124) → 90453(email.send) 已连；但 90454(email.click) 无入边，
缺少 90453 → 90454 这条边，导致 Mautic 拒绝发布（orphaned events）。
补上该边后即可 publish。
"""
import json

import mautic_client as mc

CID = 83
MISSING = ("90453", "90454")  # email.send -> email.click

cfg = mc.load_config("local")
base = cfg["base_url"]
client_id, client_secret = mc._oauth_creds(cfg)
token = mc._get_token(base, client_id, client_secret, timeout=60)

raw = mc._get(base, f"/api/campaigns/{CID}", token, timeout=30)
camp = raw.get("campaign") if isinstance(raw, dict) and "campaign" in raw else raw
cs = camp.get("canvasSettings") or {}
conns = list(cs.get("connections") or [])
print("existing connections:", len(conns))

have = {(str(c.get("sourceId")), str(c.get("targetId"))) for c in conns if isinstance(c, dict)}
src, tgt = MISSING
if (src, tgt) in have:
    print("边已存在，无需添加")
else:
    conns.append({"sourceId": src, "targetId": tgt, "anchors": {"source": "bottom", "target": "top"}})
    print(f"补边 {src} -> {tgt}")

new_cs = dict(cs)
new_cs["connections"] = conns

r = mc._patch(base, f"/api/campaigns/{CID}/edit", {"canvasSettings": new_cs}, token, timeout=60)
print("patch canvasSettings ->", r.get("status"), str(r.get("body"))[:300])

r2 = mc._patch(base, f"/api/campaigns/{CID}/edit", {"isPublished": True}, token, timeout=60)
print("publish ->", r2.get("status"), str(r2.get("body"))[:300])

raw2 = mc._get(base, f"/api/campaigns/{CID}", token, timeout=30)
c2 = raw2.get("campaign") if isinstance(raw2, dict) and "campaign" in raw2 else raw2
print("isPublished now =", c2.get("isPublished"))
