"""
Push c1 of program_nainazi-concert-2039 to the LOCAL Mautic (http://localhost:8080).
c1 strategy was enriched (objective keyword auto-detection) with:
  landing_page_ref / form_ref / main_endpoint.form / actions=[landing_page,form]
  judgment: form.submit  ->  the full chain should now create a real form + landing page
  with the form embedded, and a form.submit campaign event carrying forms:[<real_id>].

Run with approved=False (create campaign unpublished; user approves in Mautic UI).
"""
import json
import sys
import mautic_client as m

PROG = "output/program_nainazi-concert-2039.json"
d = json.load(open(PROG, encoding="utf-8"))
camps = d.get("campaigns") or []
c1 = camps[0]
proposal = c1.get("proposal")
if not proposal:
    print("ERROR: c1 has no proposal"); sys.exit(2)

name = proposal["campaign"].get("name")
# Duplicate guard: skip if a campaign with the same name already exists (avoid re-push dupes)
try:
    existing = m.mautic_read_campaigns("local").get("campaigns", {})
    for _cid, _c in (existing.items() if isinstance(existing, dict) else []):
        _n = _c.get("name") if isinstance(_c, dict) else _c
        if _n == name:
            print(f"WARN: campaign named {name!r} already exists (id={_cid}); skipping to avoid duplicate.")
            sys.exit(0)
except Exception as _ge:
    print("  (duplicate check skipped, err:", _ge, ")")

print("==> pushing c1 campaign:", name)
print("    channels:", proposal["campaign"].get("channels"),
      "reserved:", proposal["campaign"].get("reserved_channels"))
strat = (proposal["campaign"].get("strategy") or {})
mep = strat.get("main_endpoint") or {}
print("    main_endpoint.form =", mep.get("form"),
      "| landing_page =", mep.get("landing_page"),
      "| actions =", mep.get("actions"))

result = m.push(proposal, "local", approved=False)
print("\n=== PUSH RESULT ===")
for k in ("campaign_id", "name", "errors"):
    if k in result:
        print(f"  {k} = {result[k]}")
log = result.get("ensure_log") or []
print("  ensure_log assets:")
for a in log:
    print(f"    - asset={a.get('asset')} id={a.get('id')} name={a.get('name')} alias={a.get('alias')}")

cid = result.get("campaign_id")
if not cid:
    print("!! no campaign_id returned; push may have failed. errors:", result.get("errors"))
    sys.exit(3)

# Readback the created campaign and verify the form.submit event carries forms:[id]
print("\n=== READBACK campaign", cid, "===")
got = m.mautic_get_campaign(cid, "local")
camp = got.get("campaign", got)
evs = camp.get("events", [])
print("  isPublished =", camp.get("isPublished"), "| events =", len(evs) if isinstance(evs, list) else evs)
for e in (evs if isinstance(evs, list) else []):
    t = e.get("type")
    if t in ("form.submit", "lead.changetags", "page.decision"):
        props = e.get("properties") or {}
        print(f"    type={t} name={e.get('name')!r} forms={props.get('forms')} tags={props.get('tags')}")

# Verify the form asset fields + landing page html (read back from Mautic)
form_id = next((a.get("id") for a in log if a.get("asset") == "form" and a.get("id")), None)
lp_id = next((a.get("id") for a in log if a.get("asset") == "landing_page" and a.get("id")), None)
cfg = m.load_config("local")
base = cfg["base_url"]
cid_o, sec_o = m._oauth_creds(cfg)
try:
    tok = m._get_token(base, cid_o, sec_o)
    if form_id:
        f = m._get(base, f"/api/forms/{form_id}", tok, timeout=30)
        fa = f.get("form", f)
        fields = fa.get("fields", {}).get("core") or fa.get("fields") or []
        print("\n  FORM", form_id, "fields:")
        if isinstance(fields, dict):
            for fk, fv in fields.items():
                print(f"    - {fv.get('label')} ({fv.get('type')}) required={fv.get('isRequired')}")
        elif isinstance(fields, list):
            for fv in fields:
                print(f"    - {fv.get('label')} ({fv.get('type')}) required={fv.get('isRequired')}")
    if lp_id:
        p = m._get(base, f"/api/pages/{lp_id}", tok, timeout=30)
        pa = p.get("page", p)
        html = pa.get("customHtml") or ""
        print("\n  LANDING PAGE", lp_id, "name=", pa.get("title") or pa.get("name"))
        print("    contains {form=...} embed:", ("{form=" in html))
        idx = html.find("{form=")
        if idx >= 0:
            print("    embed snippet:", html[idx:idx+60])
except Exception as ex:
    print("  readback detail error:", ex)

# Best-effort cleanup of diagnostic test assets created earlier
import urllib.request as _ur
def _del(path):
    try:
        req = _ur.Request(base + path, method="DELETE")
        req.add_header("Authorization", "Bearer " + tok)
        _ur.urlopen(req, timeout=30)
        print("  cleaned up", path)
    except Exception as _e:
        print("  cleanup skip", path, "->", _e)
print("\n-- cleaning diagnostic assets --")
for _did in (11, 30, 118):
    _del(f"/api/forms/{_did}")
    _del(f"/api/pages/{_did}")
    _del(f"/api/emails/{_did}")
print("\nDONE")
