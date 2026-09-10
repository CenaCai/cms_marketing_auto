"""补记 c1 的推送状态。

背景：2026-09-10 c1 推送时，第一次请求在服务端真实建好了 Mautic campaign 83，
但被工具超时掐断；随后第二次请求因 Mautic 临时超时失败，把本地状态回滚成未部署，
导致「Mautic 有 campaign 83 / 本地显示未部署」的不一致。若再点推送会新建重复 campaign。

本脚本：把本地状态对齐到 Mautic 实际状态（不新建任何资产）。
"""
import json
import shutil
import sys

import mautic_client as mc
import cockpit

GID = "jiaa_football_2050"
CID = "c1"
CAMPAIGN_ID = 83
EMAIL_IDS = (122, 123)  # 主邮件 / 提醒邮件（从 campaign 83 的 events 里读到的真实 id）

path = f"output/program_{GID}.json"
shutil.copy(path, path + ".bak")
print("已备份 ->", path + ".bak")

cfg = mc.load_config("local")
base = cfg["base_url"]
client_id, client_secret = mc._oauth_creds(cfg)
token = mc._get_token(base, client_id, client_secret, timeout=60)
print("token OK")

# 1) 确保 campaign 83 已发布（幂等）
r = mc._patch(base, f"/api/campaigns/{CAMPAIGN_ID}/edit", {"isPublished": True}, token, timeout=60)
print("publish campaign 83 ->", r.get("status"), str(r.get("body"))[:200])

# 2) 取邮件真实名称，用于回填 ensure_log
names = {}
for eid in EMAIL_IDS:
    try:
        res = mc._get(base, f"/api/emails/{eid}", token, timeout=30)
        d = res.get("email") if isinstance(res, dict) and "email" in res else res
        names[eid] = (d or {}).get("name")
    except Exception as e:  # noqa: BLE001
        print("  get email", eid, "ERR", e)
        names[eid] = None
print("email names:", names)

# 3) 读 program，构造 ensure_log，用 push 同款函数回填 strategy
p = json.load(open(path, encoding="utf-8"))
c1 = next(c for c in p["campaigns"] if c.get("cid") == CID)
cname = ((c1.get("proposal") or {}).get("campaign") or {}).get("name") or c1.get("cid")
print("campaign name =", cname)

log = []
main_id, follow_id = EMAIL_IDS
if names.get(main_id):
    log.append({"asset": "email", "name": names[main_id], "id": main_id, "created": False})
if names.get(follow_id):
    log.append({"asset": "email", "name": names[follow_id], "id": follow_id, "created": False})

result = {
    "dry_run": False,
    "campaign_id": CAMPAIGN_ID,
    "env": "local",
    "steps": [],
    "ensure_log": log,
    "note": "2026-09-10 由 agent 依据 Mautic 实际状态补记（原成功推送记录被后续失败请求回滚）",
}
c1["proposal"]["deploy_result"] = result
c1["proposal"]["deployed"] = True
c1["status"] = "executing"

cockpit._sync_resolved_assets_to_strategy(c1, result)
s = c1.get("strategy") or {}
print("strategy.email_ref =", s.get("email_ref"), "id =", s.get("email_id"))
print("strategy.email_followup_ref =", s.get("email_followup_ref"), "id =", s.get("email_followup_id"))

cockpit._save_program(p)
print("已保存")
