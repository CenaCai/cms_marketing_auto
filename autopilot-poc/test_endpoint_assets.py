"""
test_endpoint_assets.py — 验证「stage / segment / form 资产解析」+「终点只触发判定出来的动作」
================================================================================================
对应需求：
  1) stage / segment / form 做资产解析：策略里写的是名称（"engaged" / "SEG_COLD" / "报名表"），
     要解析成 Mautic 真实 ID，才能落 lead.changestage / lead.changelist / form.submit 事件。
  2) 终点不是「声明三类就触发三类」，而是按需求判定触发一个还是多个。

覆盖：
  a. ref 形态容错（数字 / "id:3" / {"id":3} / {"ref":"x"} / 纯名字）
  b. 复用已有资产 / 自动建草稿 / 解析失败 三种结果
  c. 解析到 ID → 节点带 *_id 且落成真实 Mautic 事件（properties 带真 ID）
  d. 没解析到 → 退回审计透传（不落事件）+ 记 warning（不静默丢需求）
  e. 阶段规则（stage_rules.to）同样解析
  f. segment action=remove → removeFromLists
  g. Mautic 事件图不变量不被破坏（anchors.target=top / 无悬空连线 / newN）

纯标准库，不连真实 Mautic（用 asset_resolver.set_resolver 注入）。
"""
from __future__ import annotations

import re

import asset_resolver
from goal_intake import parse_brief
from plan_compiler import compile
from strategy_spec import compose_final_strategy

GOAL = parse_brief({
    "goal_id": "ucl2028",
    "objective": "邀请 2028 欧超决赛意向客户登记",
    "kpi": {"type": "conversion_rate", "target": 0.15},
    "audience_segment": "SEG_UCL_FANS",
    "landing_page_url": "",
})

fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        fails.append(msg)


def strat(campaign: dict, **spec_top) -> dict:
    spec = dict(spec_top)
    spec["campaigns"] = [campaign]
    s = compose_final_strategy(spec, GOAL)[0]
    s["asset_resolve"] = True          # 本文件就是要测解析，显式打开
    return s


def install(catalog: dict, allow_create_note: list):
    """注入一个假 Mautic：catalog = {(kind, name): id}；未收录则看 allow_create。"""

    def fake(kind, name, allow_create, env):
        allow_create_note.append((kind, name, allow_create))
        key = (kind, name)
        if key in catalog:
            return {"id": catalog[key], "name": name, "created": False}
        if allow_create:
            new_id = 900 + len(catalog)
            catalog[key] = new_id
            return {"id": new_id, "name": name, "created": True}
        return {"id": None, "error": "Mautic 中不存在同名资产（未自动创建）"}

    asset_resolver.reset_cache()
    asset_resolver.set_resolver(fake)


def invariants(p, label):
    events = p["mautic_events"]
    canvas = p["mautic_canvas"]
    eids = {e["id"] for e in events}
    check(all(c["anchors"].get("target") == "top" for c in canvas["connections"]),
          f"{label}：anchors.target 全部 top")
    dangling = [c for c in canvas["connections"]
                if c["sourceId"] not in eids | {"lists"} or c["targetId"] not in eids]
    check(not dangling, f"{label}：无悬空连线（{dangling}）")
    check(all(re.fullmatch(r"new\d+", e["id"]) for e in events), f"{label}：事件 id 形如 newN")


# ================================================================ a. ref 形态容错
print("\n=== a. ref 形态容错：数字 / id:3 / dict / 纯名字 ===")
asset_resolver.set_resolver(lambda k, n, a, e: {"id": 7, "created": False})
asset_resolver.reset_cache()
r1 = asset_resolver.resolve("stage", 12)
r2 = asset_resolver.resolve("stage", "id:3")
r3 = asset_resolver.resolve("stage", {"id": 5, "name": "engaged"})
r4 = asset_resolver.resolve("stage", {"ref": "engaged"})
r5 = asset_resolver.resolve("stage", "")
check(r1.id == 12 and r1.status == asset_resolver.ID_REF, f"数字 12 → id=12（{r1.status}）")
check(r2.id == 3 and r2.status == asset_resolver.ID_REF, f"'id:3' → id=3（{r2.status}）")
check(r3.id == 5 and r3.status == asset_resolver.INLINE_ID, "dict 带 id → 直接用，不查 Mautic")
check(r4.id == 7 and r4.status == asset_resolver.REUSED, "dict 只有 ref → 按名字查")
check(r5.status == asset_resolver.EMPTY and r5.id is None, "空 ref → EMPTY，不查不告警")
check(r5.warning() is None, "EMPTY 不产生 warning")

# ================================================================ b. 三种解析结果
print("\n=== b. 复用 / 自动建草稿 / 解析失败 ===")
cat = {("stage", "engaged"): 3}
calls = []
install(cat, calls)
a_reuse = asset_resolver.resolve("stage", "engaged")
a_new = asset_resolver.resolve("segment", "SEG_COLD")
check(a_reuse.id == 3 and a_reuse.status == asset_resolver.REUSED, "已有阶段 → 复用（status=reused）")
check(a_new.status == asset_resolver.CREATED and a_new.created and a_new.id is not None,
      f"没有的分组 → 自动建草稿（id={a_new.id}）")
check("自动建草稿" in (a_new.warning() or "") and "未上线" in (a_new.warning() or ""),
      "自动新建 → warning 里说明是草稿、需运营补内容后上线")
check(a_reuse.warning() is None, "复用已有资产 → 不告警")

asset_resolver.reset_cache()
asset_resolver.set_resolver(lambda k, n, a, e: {"id": None, "error": "未配置 OAuth client_id/secret"})
a_fail = asset_resolver.resolve("form", "报名表")
check(a_fail.status == asset_resolver.UNRESOLVED and a_fail.id is None, "查不到也建不了 → UNRESOLVED")
check("未解析到 Mautic 资产 ID" in (a_fail.warning() or "") and "未配置" in (a_fail.warning() or ""),
      f"失败 → warning 带上原因（{a_fail.warning()}）")

# ================================================================ c. 解析到 ID → 落成真实 Mautic 事件
print("\n=== c. 解析到 ID → lead.changestage / lead.changelist / form.submit 带真 ID ===")
cat = {("stage", "engaged"): 3, ("segment", "SEG_COLD"): 11, ("form", "FORM_SIGNUP"): 21}
calls = []
install(cat, calls)
S1 = strat({
    "cid": "c1",
    "branches": [
        {"id": "clicked", "condition": {"signal": "email.click"},
         "endpoint": {"stage": "engaged"}, "actions": ["stage"]},
        {"id": "cold", "condition": {"signal": "email.open"},
         "endpoint": {"segment": "SEG_COLD"}, "actions": ["segment"]},
        {"id": "submitted", "condition": {"signal": "form.submit", "form": "FORM_SIGNUP"},
         "endpoint": {"form": "FORM_SIGNUP"}, "actions": ["form"]},
        {"id": "newgrp", "condition": {"signal": "page.hit"},
         "endpoint": {"segment": "SEG_NEW"}, "actions": ["segment"]},
    ],
})
p1 = compile(GOAL, S1)
g1 = {n["id"]: n for n in p1["graph"]}
check(g1["n_fork_clicked_stage"]["params"].get("stage_id") == 3,
      "阶段终点解析出 stage_id=3（写进节点 params）")
check(g1["n_fork_cold_seg"]["params"].get("segment_id") == 11, "分组终点解析出 segment_id=11")
check(g1["n_fork_submitted_form"]["params"].get("form_id") == 21, "表单终点解析出 form_id=21")

m1 = {e["type"]: e for e in p1["mautic_events"]}
check("lead.changestage" in m1 and m1["lead.changestage"]["properties"] == {"stage": 3},
      f"落 Mautic lead.changestage，properties 带真 stage_id（{m1.get('lead.changestage', {}).get('properties')}）")
# 注：m1 按 type 取最后一个事件，两个分组分支各一个，故按集合断言
_changelist = {tuple(e["properties"].get("addToLists") or [])
               for e in p1["mautic_events"] if e["type"] == "lead.changelist"}
check((11,) in _changelist and len(_changelist) == 2,
      f"两个分组分支都落 lead.changelist 且带真 segment_id（{_changelist}）")
check(m1.get("form.submit", {}).get("properties", {}).get("forms") == [21],
      f"落 Mautic form.submit 且限定表单（{m1.get('form.submit', {}).get('properties')}）")
invariants(p1, "解析成功")

# 资产台账：运营能看到「哪个名字 → 哪个 ID，是复用还是新建」
rep = {r["kind"] + ":" + str(r["name"]): r for r in p1.get("asset_resolution", [])}
check(rep.get("stage:engaged", {}).get("status") == "reused", "台账记录 stage 是复用（Mautic 已有）")
check(rep.get("segment:SEG_NEW", {}).get("status") == "created",
      "台账记录未收录的分组是自动新建的草稿")
check(rep.get("segment:SEG_NEW", {}).get("created") is True, "created 标志为真（运营需补内容后上线）")
check(all("id" in r for r in p1["asset_resolution"]), "台账每条都有解析出的 id")

# ================================================================ d. 没解析到 → 审计透传 + warning
print("\n=== d. 没解析到 ID → 退回审计（不落坏事件）+ 记 warning ===")
cat = {}
calls = []
install(cat, calls)
asset_resolver.set_resolver(lambda k, n, a, e: {"id": None, "error": "Mautic 未连接"})
S2 = strat({
    "cid": "c2",
    "branches": [{"id": "clicked", "condition": {"signal": "email.click"},
                  "endpoint": {"stage": "engaged"}, "actions": ["stage"]}],
})
p2 = compile(GOAL, S2)
g2 = {n["id"]: n for n in p2["graph"]}
check("stage_id" not in g2["n_fork_clicked_stage"]["params"], "没解析到 → 节点不带 stage_id")
check("n_fork_clicked_stage" in g2, "节点仍留在事件图（审计可查，不静默丢）")
check(not [e for e in p2["mautic_events"] if e["type"] == "lead.changestage"],
      "没解析到 → 不落 lead.changestage（不会写出 stage=0 的坏动作）")
check(any("未解析到 Mautic 资产 ID" in w for w in p2.get("compile_warnings", [])),
      f"记 compile_warning（{p2.get('compile_warnings')}）")
invariants(p2, "解析失败")

# ================================================================ e. stage_rules 也解析
print("\n=== e. 阶段升降级规则的目标阶段也解析 ===")
cat = {("stage", "mql"): 5, ("stage", "lead"): 2}
install(cat, [])
S3 = strat({
    "cid": "c3",
    "stage_rules": [
        {"from": "lead", "to": "mql", "when": {"signal": "form.submit"}},
        {"from": "mql", "to": "lead", "direction": "down"},
    ],
})
p3 = compile(GOAL, S3)
g3 = {n["id"]: n for n in p3["graph"]}
check(g3["n_stage_rule_1"]["params"].get("stage_id") == 5, "升级规则 → stage_id=5")
check(g3["n_stage_rule_2"]["params"].get("stage_id") == 2, "降级规则 → stage_id=2")
st = [e for e in p3["mautic_events"] if e["type"] == "lead.changestage"]
# 注：汇聚节点会按父路径复制实例（Mautic 要求每条路径都能触发），故事件数 ≥ 2
check(len(st) >= 2 and {e["properties"]["stage"] for e in st} == {5, 2},
      f"两条规则都落成 lead.changestage（{[e['properties'] for e in st]}）")
invariants(p3, "阶段规则")

# ================================================================ f. 移出分组
print("\n=== f. segment action=remove → removeFromLists ===")
cat = {("segment", "SEG_PROMO"): 8}
install(cat, [])
S4 = strat({
    "cid": "c4",
    "branches": [{"id": "burn", "condition": {"signal": "email.open"},
                  "endpoint": {"segment": "SEG_PROMO", "action": "remove"},
                  "actions": ["segment"]}],
})
p4 = compile(GOAL, S4)
cl = [e for e in p4["mautic_events"] if e["type"] == "lead.changelist"]
check(cl and cl[0]["properties"] == {"addToLists": [], "removeFromLists": [8]},
      f"action=remove → 移出分组（{[e['properties'] for e in cl]}）")

# ================================================================ g. 只查不建
print("\n=== g. asset_auto_create=false → 只查不建 ===")
cat = {}
calls = []
install(cat, calls)
S5 = strat({
    "cid": "c5",
    "branches": [{"id": "clicked", "condition": {"signal": "email.click"},
                  "endpoint": {"stage": "nope"}, "actions": ["stage"]}],
})
S5["asset_auto_create"] = False
p5 = compile(GOAL, S5)
check(any(a is False for (_, _, a) in calls), f"allow_create=False 传到了解析器（{calls}）")
check(not [e for e in p5["mautic_events"] if e["type"] == "lead.changestage"],
      "只查不建 → 查不到就不落事件（不写脏数据进 Mautic）")

# ================================================================ h. 整体关闭解析
print("\n=== h. asset_resolve=false → 完全不碰 Mautic（离线跑批/单测）===")
blown = []
install({}, [])
asset_resolver.set_resolver(lambda k, n, a, e: blown.append((k, n)) or {"id": 1})
S6 = strat({
    "cid": "c6",
    "branches": [{"id": "clicked", "condition": {"signal": "email.click"},
                  "endpoint": {"stage": "engaged"}, "actions": ["stage"]}],
})
S6["asset_resolve"] = False
p6 = compile(GOAL, S6)
check(not blown, f"asset_resolve=false → 解析器一次都没被调用（{blown}）")
check(not [e for e in p6["mautic_events"] if e["type"] == "lead.changestage"],
      "关闭解析 → 与改动前一致（阶段只审计）")

asset_resolver.clear_resolver()
asset_resolver.reset_cache()

print("\n=== 汇总 ===")
if fails:
    print(f"\n❌ {len(fails)} 项失败：")
    for f in fails:
        print("  - " + f)
    raise SystemExit(1)
print("\n✅ 全部通过（stage/segment/form 解析成真实 ID 并落成 Mautic 原生事件；"
      "解析不到退回审计并告警；终点只触发判定出来的动作）")
