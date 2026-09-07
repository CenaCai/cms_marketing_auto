import json, sys, os
sys.path.insert(0, r"C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc")
from strategy_spec import (parse_strategy_spec, strategies_from_spec,
                           service_sequences_from_spec, spec_goal_defaults)

A = r"C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc\strategies\ucl2028_send_strategy.json"
B = r"C:\Users\cenacai\WorkBuddy\2026-08-31-18-52-03\autopilot-poc\strategies\ucl2028_content_map.json"

variants = {
    "list": [A, B],
    "comma": A + "," + B,
    "newline": A + "\n" + B,
    "single": A,
}
results = {}
for name, src in variants.items():
    spec = parse_strategy_spec(src)
    cs = strategies_from_spec(spec)
    ss = service_sequences_from_spec(spec)
    segs = [c["segment"] for c in cs]
    results[name] = {
        "campaigns": len(cs),
        "distinct_segments": len(set(segs)),
        "segments": segs,
        "c1_email_ref": cs[0]["email_ref"],
        "modes": {c["cid"]: c["email_mode"] for c in cs},
        "lp_urls": sorted({c["landing_page_url"] for c in cs}),
        "c5_deferred": next(c["deferred"] for c in cs if c["cid"] == "ucl2028_c5"),
        "c5_cond": (next(c["deferred_enable_condition"] for c in cs if c["cid"] == "ucl2028_c5") or "")[:60],
        "service": len(ss),
        "svc_sid": ss[0]["sid"] if ss else None,
        "svc_email": ss[0]["email_ref"] if ss else None,
        "svc_subject": ss[0]["subject"] if ss else None,
        "svc_exempt_qh": ss[0]["send_conditions"]["quiet_hours_exempt"] if ss else None,
        "svc_within": ss[0]["send_conditions"]["send_within_minutes"] if ss else None,
        "svc_variant": ss[0]["content_variant_spec"]["id"] if ss else None,
        "n_sources": len(spec.get("_sources", [])),
    }
    print("=== input:", name)
    print(json.dumps(results[name], ensure_ascii=False, indent=1))

# 三种输入一致性
keys = ["campaigns", "distinct_segments", "c1_email_ref", "lp_urls", "c5_deferred", "service"]
same = all(all(results[v][k] == results["list"][k] for k in keys) for v in ("comma", "newline"))
print("多输入一致(list/comma/newline):", same)
print("单路径仍可用:", results["single"]["campaigns"] == 5, "单路径 distinct seg:", results["single"]["distinct_segments"])
print("合并后 c1 subject:", strategies_from_spec(parse_strategy_spec([A, B]))[0]["subject"][:60])
print("合并后 c1 tags:", strategies_from_spec(parse_strategy_spec([A, B]))[0]["tags_to_write"])
