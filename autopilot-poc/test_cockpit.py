import os
import json
import urllib.parse
import urllib.request as u, urllib.error

# 单元验证外链构造器（不依赖活服务）
import cockpit as C  # noqa: E402

BASE = os.environ.get("COCKPIT_BASE", "http://127.0.0.1:8090")
HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE_SPEC = os.path.join(HERE, "strategies", "example_strategy.json")

class NoRedirect(u.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

op = u.build_opener(u.ProxyHandler({}), NoRedirect)

def get(path):
    return op.open(BASE + path, timeout=10).read().decode()

def post(path, data: str):
    req = u.Request(BASE + path, data=data.encode(), method="POST")
    try:
        r = op.open(req, timeout=10)
        return r.status, r.headers.get("Location"), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location"), e.read().decode()

def post_json(path, obj: dict):
    req = u.Request(BASE + path, data=json.dumps(obj, ensure_ascii=False).encode(),
                    method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        r = op.open(req, timeout=10)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def check(name, cond, extra=""):
    print(("✅" if cond else "❌"), name, extra)


# ---------- 单元：Mautic 外链构造器（mock 资产读取，不依赖活服务/Mautic） ----------
C.mautic_read_assets = lambda env: {
    "available": True,
    "emails": [{"id": 99, "name": "EM_X", "alias": "EM_X"}],
    "segments": [{"id": 7, "name": "SEG_Y", "alias": "SEG_Y"}],
    "pages": [{"id": 3, "name": "LP_Z", "alias": "LP_Z"}],
}
_idx = C._mautic_asset_index()
check("外链索引 email 解析", _idx["email"].get("EM_X") == 99, f"id={_idx['email'].get('EM_X')}")
check("外链索引 segment 解析", _idx["segment"].get("SEG_Y") == 7)
check("外链 战役 URL", "/s/campaigns/123" in C._mautic_ext_link("campaign", "123", _idx),
      C._mautic_ext_link("campaign", "123", _idx))
check("外链 邮件 URL", "/s/emails/99/view" in C._mautic_ext_link("email", "EM_X", _idx),
      C._mautic_ext_link("email", "EM_X", _idx))
check("外链 分群 URL", "/s/segments/7" in C._mautic_ext_link("segment", "SEG_Y", _idx))
check("外链 落页 URL", "/s/landingpages/3" in C._mautic_ext_link("landingpage", "LP_Z", _idx))
check("外链 未连接返回空", C._mautic_ext_link("email", "NOPE", _idx) == "")
check("外链 未找到返回空", C._mautic_ext_link("email", "MISSING", _idx) == "")
# 直接渲染 program 验证 wave→campaign 重命名（不依赖 Mautic 连通）
_p = C._load_program("ucl2028_svctest")
if _p:
    _html = C._program_body(_p, "")
    check("program 渲染 wave→campaign 重命名", "campaign_1" in _html and "wave_1" not in _html)
    # 端到端：已推送拿到 campaign_id → 卡片渲染战役外链（email/segment 因 Mautic 未连通显示无对应）
    import copy as _copy
    _demo = _copy.deepcopy(_p)
    _demo["campaigns"][0]["proposal"]["deploy_result"] = {"campaign_id": "555", "dry_run": False}
    _demo_html = C._program_body(_demo, "")
    check("已推送 campaign 渲染战役外链", "/s/campaigns/555" in _demo_html,
          "campaign_id=555 → /s/campaigns/555")
else:
    check("program 渲染 wave→campaign 重命名", False, "（output/program_ucl2028_svctest.json 缺失）")

def program_of(gid):
    return json.load(open(os.path.join(HERE, "output", f"program_{gid}.json"), encoding="utf-8"))

# ---------- 首页 + brief 页 ----------
check("首页", "活动驾驶舱" in get("/"))
bf = get("/brief")
check("Brief 含运营目标字段", "营销目标" in bf)
check("Brief 目标字段默认空", "UEFA" not in bf and "name='objective'" in bf)
check("Brief 含目标名称字段", "name='goal_name'" in bf)
check("Brief 含总体转化率字段", "name='overall_conv'" in bf)
check("Brief 单campaign点击率改为系统反推(只读)",
      "name='click_rate_disp'" in bf and "name='click_rate'" not in bf)
check("Brief 含「用 WorkBuddy 生成策略」按钮", "gen-strategy-btn" in bf)
check("Brief 展示策略生成说明(端点优先/降级)",
      ("已配置策略自动生成端点" in bf) or ("未配置自动生成端点" in bf))
check("Brief 含约束字段", "name='constraints'" in bf)
check("Brief 含 StrategySpec 字段", "name='strategy_spec'" in bf)
check("Brief StrategySpec 已译中文", "策略规格（Agent 产出，可选）" in bf)
check("Brief 语言为下拉(中文/英文)", "中文" in bf and "英文" in bf and "name='locale'" in bf)
check("Brief 预算字段已重标无营收", "无营收活动" in bf)
check("Brief 不再让运营填分群", "name='audience_segment'" not in bf)
check("Brief 不再让运营填 KPI/落页/波次数",
      "name='kpi_target'" not in bf and "name='landing_page_url'" not in bf
      and "name='n_campaigns'" not in bf)
check("Brief 含 Agent 自动决策面板", "Agent 自动决策" in bf)
check("未提交策略时提示默认递进", "Agent 尚未产出策略" in bf)
check("Brief 不暴露频次闸门编辑", "频次闸门 1/24h" in bf and "name='max_per_24h'" not in bf)

# ---------- wave→campaign 实时校验（svctest 详情页） ----------
svc = get("/program/ucl2028_svctest")
check("svctest 详情 wave→campaign 重命名", "campaign_1" in svc and "wave_1" not in svc)
check("svctest 详情含返回按钮", "返回" in svc and "history.back()" in svc)

# ---------- /brief?spec= 预览 Agent 策略（只读摘要）----------
pv = get("/brief?spec=" + EXAMPLE_SPEC.replace(os.sep, "/"))
check("策略预览含摘要标题", "策略摘要（只读" in pv)
check("策略预览含 rationale/evidence", "理由：" in pv and "依据：" in pv)
check("策略预览 generate 邮件显示[待生成]", "[待生成]" in pv)

# ---------- 路径 A：未提交 StrategySpec → 默认递进策略（按日期跨度派生 N）----------
st, loc, _ = post("/brief",
    "objective=TEST+GOAL&locale=zh_CN&budget=0&"
    "start_date=2028-05-01&end_date=2028-07-09&"
    "constraints=22%3A00-09%3A00+%E5%85%8D%E6%89%93%E6%89%B0")
check("Brief→302 Program", st == 302, f"loc={loc}")
gid = loc.split("/")[-1]

ph = get(f"/program/{gid}")
check("Program 含 3 campaign", ("campaign_1" in ph) and ("campaign_3" in ph))
check("Program 含治理节点", "sourcemarketing.frequency_gate" in ph)
check("Program 事件图渲染为流程图", "<svg" in ph)
check("Program 含 Mautic 资产清单", "Mautic 资产清单" in ph)
check("Program 含每campaign目标编辑", "name='conv_target'" in ph)
check("Program 头部展示目标名称", "目标名称" in ph)
check("Program 展示运营约束", "免打扰" in ph)
check("Program 标记默认策略来源", "默认递进策略" in ph)
check("Program 首波初始为未审核", "未审核" in ph)
check("Program 含派生计划摘要(系统反推点击率)", "派生计划摘要" in ph)
check("Program 告知合理性判定", "合理性判定" in ph)
check("Program 含 Agent 优化说明", "Agent 优化说明" in ph)
check("Program 反推点击率字段已落库", "click_rate" in program_of(gid)["plan"])

c1 = f"{gid}_c1"
st, _, body = post(f"/program/{gid}/campaign/{c1}/approve", "approver=alice")
check("campaign 审批 APPROVED", "APPROVED" in body)

pp = f"output/program_{gid}.json"
prog = json.load(open(pp, encoding="utf-8"))
c = next(x for x in prog["campaigns"] if x["cid"] == c1)
c["proposal"]["graph"][0]["type"] = "TAMPERED"
json.dump(prog, open(pp, "w", encoding="utf-8"))
st, _, body = post(f"/program/{gid}/campaign/{c1}/approve", "approver=bob")
check("篡改后审批 REJECTED", "REJECTED" in body)
c["proposal"]["graph"][0]["type"] = "decision.segment"
json.dump(prog, open(pp, "w", encoding="utf-8"))

st, _, body = post(f"/program/{gid}/complete", f"cid={c1}&conversion=0.05&unsub=0.001")
check("完成回写触发自适应", "下游改写" in body)
check("完成首波→状态 done_met/done_below",
      json.load(open(pp, encoding="utf-8"))["campaigns"][0]["status"] in ("done_met", "done_below"))
prog = json.load(open(pp, encoding="utf-8"))
c2 = next(x for x in prog["campaigns"] if x["cid"] == f"{gid}_c2")
sc = c2["strategy"]["send_conditions"]
check("下游提频(乏力: +2)", sc["max_per_24h"] >= 3, f"max_per_24h={sc['max_per_24h']}")
check("下游换内容变体", c2["strategy"]["content_variant"] >= 1)
check("下游加 broaden/reengage tag", ("broaden" in c2["strategy"]["tags_to_write"]))
check("下游重算 plan_hash", c2["proposal"]["plan_hash"])

c2id = f"{gid}_c2"
st, _, body = post(f"/program/{gid}/complete", f"cid={c2id}&conversion=0.30&unsub=0.001")
prog = json.load(open(pp, encoding="utf-8"))
c3 = next(x for x in prog["campaigns"] if x["cid"] == f"{gid}_c3")
check("达标下游降本(降频)", c3["strategy"]["send_conditions"]["max_per_24h"] <= 2,
      f"max_per_24h={c3['strategy']['send_conditions']['max_per_24h']}")

# ---------- 路径 B：提交 Agent StrategySpec → N 由 campaigns 决定 ----------
st, loc, body = post("/brief", "objective=UCL+2028&strategy_spec=" + EXAMPLE_SPEC.replace(os.sep, "/"))
check("StrategySpec Brief→302 Program", st == 302, f"loc={loc} {body[:120]}")
gid2 = loc.split("/")[-1]
prog2 = program_of(gid2)
check("策略路径生成 2 个 campaign", prog2["n_campaigns"] == 2,
      f"n={prog2['n_campaigns']}")
cids = [c["cid"] for c in prog2["campaigns"]]
check("cid 取自 StrategySpec", cids == ["ucl2028_c1", "ucl2028_c2"], f"{cids}")
segs = [c["strategy"]["segment"] for c in prog2["campaigns"]]
check("两个 campaign 分群不同", len(set(segs)) == 2, f"{segs}")
modes = [c["strategy"]["email_mode"] for c in prog2["campaigns"]]
check("一个 reuse 一个 generate", modes == ["reuse", "generate"], f"{modes}")
check("reuse 用真实资产 ID",
      prog2["campaigns"][0]["strategy"]["email_ref"] == "EM_UCL2028_TICKET_V1")
hashes = [c["proposal"]["plan_hash"] for c in prog2["campaigns"]]
check("两份 proposal plan_hash 不同", hashes[0] != hashes[1],
      f"{hashes[0][:12]}… vs {hashes[1][:12]}…")
pg2 = get(f"/program/{gid2}")
check("Program 页展示策略理由/依据", "理由：" in pg2 and "依据：" in pg2)
check("Program 页展示[待生成]邮件", "[待生成]" in pg2)
check("Program 页展示变体 headline", "你的优先购票通道已开启" in pg2)
check("Program 标记 Agent 策略来源", "Agent 策略" in pg2)

# ---------- 路径 C：service 序列 + deferred 波次 + KPI 未设置 ----------
# （贴 JSON 文本提交，验证 service 与 promo 解耦、deferred 不自动发、R 未给不算达成率）
SPEC_C = {
    "goal_id": "ucl2028_svctest",
    "objective": "UCL 2028 意向登记（service 解耦 + deferred 验证）",
    "kpi": {"metric": "conversion", "target": 0.0},
    "locale": ["zh_CN"],
    "campaigns": [
        {"cid": "svctest_c1", "name": "种子波",
         "segment": {"mode": "propose", "ref": "SEG_SEED"},
         "send_conditions": {"delay_hours": 0, "max_per_24h": 1, "max_per_7d": 1,
                             "quiet_hours": "22:00-09:00"},
         "tags_to_write": ["svctest_invited"]},
        {"cid": "svctest_c2", "name": "host 确认波（deferred）", "deferred": True,
         "segment": {"mode": "propose", "ref": "SEG_HOST_POOL"},
         "send_conditions": {"delay_hours": 264, "max_per_24h": 1, "max_per_7d": 2},
         "tags_to_write": ["svctest_host"]},
    ],
    "service_sequences": [
        {"sid": "svc_svctest_confirm", "name": "登记确认件", "intent": "service",
         "class": "service", "counts_toward_promo_cap": False,
         "exempt_from_promo_suppression": True, "quiet_hours_exempt": True,
         "send_within_minutes": 5,
         "trigger": {"mode": "event", "event": "表单提交成功", "delay_hours": 0},
         "tags_to_write": ["svctest_registered"]},
    ],
}
st, loc, body = post("/brief", "objective=svctest&strategy_spec="
                     + urllib.parse.quote(json.dumps(SPEC_C, ensure_ascii=False)))
check("service/deferred Brief→302", st == 302, f"loc={loc} {body[:150]}")
gid3 = loc.split("/")[-1]
prog3 = program_of(gid3)
check("promo 仍为 2 波（service 不混入）", prog3["n_campaigns"] == 2)
check("service 序列单独挂载", prog3.get("n_service_sequences") == 1)
sts = {c["cid"]: c["status"] for c in prog3["campaigns"]}
check("c5/c2 置为 deferred", sts.get("svctest_c2") == "deferred", f"{sts}")
check("非 deferred 波初始为未审核", sts.get("svctest_c1") == "unreviewed")
svc3 = prog3["service_sequences"][0]
gtypes3 = [n["type"] for n in svc3["proposal"]["graph"]]
check("service 不注入 promo 频次闸门", not any("frequency_gate" in t for t in gtypes3), f"{gtypes3}")
check("service 不注入锚点仲裁", not any("anchor" in t for t in gtypes3))
gr3 = next(n for n in svc3["proposal"]["graph"] if n["id"] == "n_guardrail")
check("service 护栏豁免 suppress_promo/comm_freeze",
      "suppress_promo" in gr3["params"].get("exempt_from", [])
      and "comm_freeze" in gr3["params"].get("exempt_from", []))
check("service 事件触发（不看 segment）",
      svc3["proposal"]["graph"][0]["type"] == "decision.event_trigger"
      and svc3["strategy"]["segment"] == "")
check("tag 经 tag-rule 通路写入",
      next(n for n in svc3["proposal"]["graph"] if n["id"] == "n_tag")["params"]["via"] == "tag_rule")
check("service 状态为 armed（不进 promo 排期）", svc3["status"] == "armed")
# deferred 波：推送须被拒；启用后转 pending
st, _, body = post(f"/program/{gid3}/campaign/svctest_c2/activate", "")
check("deferred 波可启用", "已启用" in body, f"st={st}")
prog3 = program_of(gid3)
check("启用后转未审核（回到标准通道）",
      next(c for c in prog3["campaigns"] if c["cid"] == "svctest_c2")["status"] == "unreviewed")
# KPI target=0 → 目标未设置，不做达成率改写
st, _, body = post(f"/program/{gid3}/complete", "cid=svctest_c1&conversion=0.02&unsub=0.001")
check("KPI 未设置时不做达成率改写", "未设置" in body, f"{body[:120]}")
prog3 = program_of(gid3)
c2b = next(c for c in prog3["campaigns"] if c["cid"] == "svctest_c2")
check("KPI 未设置：不提频不加 urgency/broaden",
      c2b["strategy"]["send_conditions"]["max_per_24h"] == 1
      and not ({"urgency", "broaden", "reengage"} & set(c2b["strategy"]["tags_to_write"])))
pg3 = get(f"/program/{gid3}")
check("Program 页渲染服务序列区块", "服务序列（service/transactional）" in pg3)
check("Program 页提示 KPI 未设置", "KPI 目标值未设置" in pg3)

# ---------- 路径 D：多文件合并（send_strategy + content_map）----------
SEND = os.path.join(HERE, "strategies", "ucl2028_send_strategy.json").replace(os.sep, "/")
CONTENT = os.path.join(HERE, "strategies", "ucl2028_content_map.json").replace(os.sep, "/")
BOTH = SEND + "," + CONTENT
pv2 = get("/brief?spec=" + BOTH)
check("多文件预览显示合并徽章", "已合并 2 个策略文件" in pv2)
st, loc, body = post("/brief", "objective=UCL&strategy_spec=" + urllib.parse.quote(BOTH))
check("多文件 Brief→302", st == 302, f"loc={loc}")
gid4 = loc.split("/")[-1]
prog4 = program_of(gid4)
cs4 = prog4["campaigns"]
segs4 = [c["strategy"]["segment"] for c in cs4]
check("合并后 campaigns=5", len(cs4) == 5, f"n={len(cs4)}")
check("DISTINCT segment=5", len(set(segs4)) == 5, f"{sorted(set(segs4))}")
check("c1 复用真实资产 EM_UCL2028_INVITE",
      cs4[0]["strategy"]["email_ref"] == "EM_UCL2028_INVITE", cs4[0]["strategy"]["email_ref"])
modes4 = {c["cid"]: c["strategy"]["email_mode"] for c in cs4}
check("c3/c4/c5 为 generate",
      modes4.get("ucl2028_c3") == "generate" and modes4.get("ucl2028_c4") == "generate"
      and modes4.get("ucl2028_c5") == "generate", f"{modes4}")
lp4 = sorted({c["strategy"]["landing_page_url"] for c in cs4})
check("落页 URL 来自 content_map",
      lp4 == ["http://localhost:8080/s/ucl2028-bridge"], f"{lp4}")
c5_4 = next(c for c in cs4 if c["cid"] == "ucl2028_c5")
check("c5 状态 deferred", c5_4["status"] == "deferred")
check("c5 带启用条件说明", bool(c5_4["strategy"].get("deferred_enable_condition")))
check("service 恰好 1 条", prog4.get("n_service_sequences") == 1)
s4 = prog4["service_sequences"][0]
check("service 正文来自 content_map", "已收到你的 2028 欧冠决赛" in s4["strategy"]["subject"])
check("service 声明静默窗豁免 ≤5min",
      s4["strategy"]["send_conditions"]["quiet_hours_exempt"] is True
      and s4["strategy"]["send_conditions"]["send_within_minutes"] == 5)
gr4 = next(n for n in s4["proposal"]["graph"] if n["id"] == "n_guardrail")
check("豁免写入事件图（可审计）", gr4["params"].get("quiet_hours_exempt") is True)
# 审批门：未确认豁免 → 驳回；确认后 → 通过
st, _, body = post(f"/program/{gid4}/service/{s4['sid']}/approve", "approver=alice")
check("未确认静默窗豁免 → REJECTED", "REJECTED" in body)
st, _, body = post(f"/program/{gid4}/service/{s4['sid']}/approve",
                   "approver=alice&ack_quiet_exempt=on")
check("确认豁免后 → APPROVED", "APPROVED" in body)
pg4 = get(f"/program/{gid4}")
check("Program 页明示静默窗豁免", "已豁免静默窗" in pg4)

print("DONE gid=", gid, " gid2=", gid2, " gid3=", gid3, " gid4=", gid4)

# ---------- 路径 E：提交总体目标转化率 → 系统反推单campaign点击率 + 合理性 ----------
st, loc, _ = post("/brief",
    "objective=CONV+GOAL&locale=zh_CN&budget=0&"
    "start_date=2028-05-01&end_date=2028-07-09&"
    "overall_conv=0.15")
check("Conv Brief→302 Program", st == 302, f"loc={loc}")
gid5 = loc.split("/")[-1]
ph5 = get(f"/program/{gid5}")
prog5 = program_of(gid5)
check("Conv 派生 click_rate>0", prog5["plan"]["click_rate"] > 0, f"cr={prog5['plan']['click_rate']}")
check("Conv 合理(reasonable=True)", prog5["plan"]["reasonable"] is True, f"n={prog5['plan']['n_campaigns']}")
check("Conv campaign 数受日期跨度约束(1<=n<=8)",
      1 <= prog5["plan"]["n_campaigns"] <= 8, f"n={prog5['plan']['n_campaigns']}")
check("Conv per_campaign_target=oc/n",
      abs(prog5["plan"]["per_campaign_target"] - round(0.15 / prog5["plan"]["n_campaigns"], 4)) < 1e-9,
      f"t={prog5['plan']['per_campaign_target']}")
check("Conv Program 展示反推点击率+合理性", "推算" in ph5 and "合理性判定" in ph5)
check("Conv Program 展示 Agent 优化说明", "Agent 优化说明" in ph5)

# ---------- 路径 F：高目标 + 短跨度 → 点击率超阈值，标记「需优化」 ----------
st, loc, _ = post("/brief",
    "objective=HIGH+GOAL&locale=zh_CN&budget=0&"
    "start_date=2028-06-01&end_date=2028-06-30&"
    "overall_conv=0.50")
check("HighConv Brief→302 Program", st == 302, f"loc={loc}")
gid6 = loc.split("/")[-1]
prog6 = program_of(gid6)
check("HighConv 标记需优化(reasonable=False)",
      prog6["plan"]["reasonable"] is False, f"cr={prog6['plan']['click_rate']} n={prog6['plan']['n_campaigns']}")
check("HighConv 优化说明指向超阈值压缩节奏", "超阈值" in prog6["plan"]["optimization_note"])

# ---------- 路径 G：策略生成按钮后端（无端点 → 降级复制提示词） ----------
st_g, body_g = post_json("/brief/generate-strategy",
    {"goal_name": "SMOKE", "objective": "2028 欧冠决赛邀请", "start_date": "2028-05-01",
     "end_date": "2028-07-09", "overall_conv": "0.15", "budget": "0", "locale": "zh_CN",
     "constraints": "22:00-09:00 免打扰"})
gj = json.loads(body_g)
check("策略生成端点返回 JSON", st_g == 200 and isinstance(gj, dict), f"st={st_g}")
check("无端点时降级 fallback=True", gj.get("fallback") is True, f"{gj.get('error','')}")
check("降级返回自包含提示词", "StrategySpec" in gj.get("prompt", ""))
check("提示词含 Brief 目标", "2028 欧冠决赛邀请" in gj.get("prompt", ""))

print("DONE2 gid5=", gid5, " gid6=", gid6)
