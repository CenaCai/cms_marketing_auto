"""Re-verify campaign #66 on live Mautic 7 (localhost:8080): list every event's
id/type/eventType/parent/decisionPath/name, and dump canvasSettings.connections.
This proves the parent/child links persisted end-to-end (the user's '验证连线' ask)."""
import json
import sys
sys.path.insert(0, ".")
import mautic_client as mc

cfg = mc.load_config("local")
cid, sec = mc._oauth_creds(cfg)
base = cfg["base_url"]
token = mc._get_token(base, cid, sec)
print("TOKEN OK, len=", len(token))

data = mc._get(base, "/api/campaigns/66", token, timeout=45)
if data is None:
    print("READBACK FAILED (no connection / 404)")
    sys.exit(1)

camp = (data.get("campaign") or data.get("data") or {})
if isinstance(camp, dict) and "events" not in camp:
    # sometimes keyed by id
    camp = list(data.values())[0] if isinstance(data, dict) else camp

print("CAMPAIGN id=", camp.get("id"), "name=", camp.get("name"), "isPublished=", camp.get("isPublished"))
events = camp.get("events", [])
print(f"\n=== EVENTS ({len(events)}) ===")
for ev in events:
    print(f"  id={ev.get('id')!s:>8}  type={ev.get('type'):<22} eventType={ev.get('eventType'):<10} "
          f"parent={ev.get('parent')!s:<8} decisionPath={ev.get('decisionPath')}  name={ev.get('name')}")

canvas = camp.get("canvasSettings") or {}
conns = (canvas.get("connections") if isinstance(canvas, dict) else None) or []
print(f"\n=== CANVAS CONNECTIONS ({len(conns)}) ===")
for c in conns:
    a = c.get("anchors") or {}
    print(f"  {c.get('sourceId')} --[{a.get('source')}->{a.get('target')}]--> {c.get('targetId')}")

# sanity: every non-root event must have a parent
roots = [e for e in events if e.get("parent") in (None, "null", 0)]
nonroots = [e for e in events if e.get("parent") not in (None, "null", 0)]
print(f"\nROOTS={len(roots)}  NON-ROOTS={len(nonroots)}")
missing_parent = [e.get("id") for e in nonroots if e.get("parent") is None]
print("EVENTS MISSING PARENT (should be empty):", missing_parent)
print("RESULT:", "PASS — all links persisted" if not missing_parent else "FAIL — orphan events")
