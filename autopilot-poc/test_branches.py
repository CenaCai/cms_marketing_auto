"""
test_branches.py — 验证「策略规格真正驱动 分叉 / 条件 / 终点 / 阶段升降级 / 主流程终点」
以及「画像包 + 策略规划 + 属性 = 最终总策略」的合并优先级。

纯标准库，无需服务；与 test_refactor.py 同款 check() 风格。

覆盖：
  1. branches：数组 / id→对象 两种写法，condition 与 when 都收
  2. endpoint：tags / stage / segment / email / landing_page / form / terminal 归一化
  3. stage_rules：方向缺省 up、显式 down
  4. main_endpoint + judgment
  5. 老 spec 回归：旧键一个不少、值不变（只多出新键）
  6. 优先级：红线 quiet_hours > 规格 > 画像包 > 常量
  7. 画像包富化：content_direction / visual_direction / cta_templates
"""
from __future__ import annotations

import json

import audience_map
import strategy_spec as S
from strategy_spec import (compose_final_strategy, normalize_campaign,
                           parse_quiet_hours, strategies_from_spec)

fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        fails.append(msg)


# 旧版 normalize_campaign 返回的全部键（回归基准：只增不减、不改名）
OLD_KEYS = [
    "cid", "wave_id", "variant_id", "campaign_name", "strategy_source", "intent",
    "counts_toward_promo_cap", "segment", "segment_mode", "segment_note",
    "email_ref", "email_mode", "email_pending", "email_brief", "email_followup_ref",
    "subject", "followup_subject", "content_variant", "content_variant_spec",
    "landing_page_ref", "landing_page_mode", "landing_page_note", "landing_page_url",
    "send_conditions", "tags_to_write", "rationale", "evidence", "success_criteria",
    "locales", "discount", "journey", "judgment", "deferred", "deferred_reason",
    "deferred_enable_condition", "trigger", "tag_triggers", "tag_warnings",
]
NEW_KEYS = ["window", "branches", "stage_rules", "main_endpoint",
            "content_direction", "visual_direction", "cta_templates", "_compose"]

print("\n=== 1. branches：数组写法 / when 条件 ===")
C_LIST = {
    "cid": "c1", "name": "首波",
    "segment": {"mode": "reuse", "ref": "SEG_A"},
    "email": {"mode": "reuse", "ref": "EM_A", "brief": {"subject": "S"}},
    "branches": [
        {"id": "clicked", "when": {"signal": "email.click", "op": ">=", "value": 1},
         "endpoint": {"tags": ["clicked"], "stage": "engaged", "segment": "SEG_HOT",
                      "email": "EM_B", "landing_page": "LP_B", "form": "FORM_B",
                      "terminal": True}},
        {"id": "opened", "condition": {"signal": "email.open", "op": ">=", "value": 2},
         "next": "clicked"},
    ],
}
s = normalize_campaign(C_LIST, 0)
check(len(s["branches"]) == 2, "数组写法解析出 2 个分叉（分叉数量由 spec 决定）")
b0 = s["branches"][0]
check(b0["id"] == "clicked", "branch id 保留")
check(b0["condition"] == {"signal": "email.click", "op": ">=", "value": 1},
      "when 等价于 condition（条件归一化）")
ep = b0["endpoint"]
check(ep["tags"] == ["clicked"] and ep["stage"] == "engaged" and ep["segment"] == "SEG_HOT",
      "分支终点 tag / 阶段 / 分组 解析")
check(ep["email"] == "EM_B" and ep["landing_page"] == "LP_B" and ep["form"] == "FORM_B",
      "分支终点 邮件 / 落地页 / 表单 解析")
check(ep["terminal"] is True, "分支终点 terminal=True 解析")
b1 = s["branches"][1]
check(b1["condition"] == {"signal": "email.open", "op": ">=", "value": 2},
      "condition 写法解析")
check(b1["next"] == "clicked", "分支 next 指向下一分支")
check(b1["endpoint"]["terminal"] is False, "未声明 terminal → False")

print("\n=== 2. branches：id→对象 写法 / 字符串条件简写 ===")
C_DICT = {
    "cid": "c2",
    "branches": {
        "clicked": {"when": "email.click >= 1", "endpoint": {"tag": "clicked"}},
        "no_open": {"condition": {"signal": "email.open"}},
    },
}
s2 = normalize_campaign(C_DICT, 0)
ids = [b["id"] for b in s2["branches"]]
check(ids == ["clicked", "no_open"], f"id→对象 写法解析出 {ids}")
check(s2["branches"][0]["condition"] == {"signal": "email.click", "op": ">=", "value": 1},
      "字符串条件 'email.click >= 1' 解析")
check(s2["branches"][0]["endpoint"]["tags"] == ["clicked"], "endpoint.tag 单值归一成数组")
check(s2["branches"][1]["condition"] == {"signal": "email.open", "op": "exists", "value": True},
      "只有 signal 的条件 → op=exists, value=True")

print("\n=== 3. stage_rules：阶段升降级 ===")
C_STAGE = {
    "cid": "c3",
    "stage_rules": [
        {"from": "lead", "to": "mql", "when": {"signal": "form.submit", "op": ">=", "value": 1}},
        {"from": "mql", "to": "lead", "when": "email.unsub", "direction": "down"},
    ],
}
s3 = normalize_campaign(C_STAGE, 0)
check(len(s3["stage_rules"]) == 2, "stage_rules 解析 2 条")
check(s3["stage_rules"][0]["direction"] == "up", "未写 direction → 默认 up（升级）")
check(s3["stage_rules"][1]["direction"] == "down", "显式 direction=down（降级）")
check(s3["stage_rules"][0]["when"] == {"signal": "form.submit", "op": ">=", "value": 1},
      "阶段规则条件解析")
s3b = normalize_campaign({"cid": "c3b", "stage_transitions": [
    {"from": "lead", "to": "sql", "if": {"signal": "page.hit", "value": 3}}]}, 0)
check(len(s3b["stage_rules"]) == 1 and s3b["stage_rules"][0]["to"] == "sql",
      "stage_transitions 别名 + if 别名 解析")

print("\n=== 4. main_endpoint：主流程终点 + 终点判断 ===")
C_MAIN = {
    "cid": "c4",
    "main_endpoint": {
        "tags": ["converted"], "stage": "customer", "terminal": True,
        "judgment": {"signal": "page.hit", "op": ">=", "value": 2},
    },
}
s4 = normalize_campaign(C_MAIN, 0)
me = s4["main_endpoint"]
check(me["tags"] == ["converted"] and me["stage"] == "customer", "主流程终点 tag / 阶段解析")
check(me["judgment"] == {"signal": "page.hit", "op": ">=", "value": 2}, "终点判断解析")
check(me["terminal"] is True, "主流程终点 terminal=True")
s4b = normalize_campaign({"cid": "c4b", "endpoint": {"stage": "churned"}}, 0)
check(s4b["main_endpoint"]["stage"] == "churned" and s4b["main_endpoint"]["terminal"] is True,
      "endpoint 别名解析，且主终点默认 terminal=True")
check(s4b["main_endpoint"]["judgment"] is None, "未写判断 → judgment=None")
s4c = normalize_campaign({"cid": "c4c"}, 0)
check(s4c["main_endpoint"] == {"tags": [], "stage": None, "segment": None, "email": None,
                               "landing_page": None, "form": None, "terminal": True,
                               "judgment": None},
      "无任何终点声明 → 全空但结构完整")

print("\n=== 5. 老 spec 回归（旧键一个不少、值不变）===")
OLD_C = {
    "cid": "old_c1", "name": "老规格首波",
    "segment": {"mode": "reuse", "ref": "SEG_OLD", "note": "n"},
    "email": {"mode": "reuse", "ref": "EM_OLD",
              "brief": {"subject": "老主题", "angle": "权益", "cta": "购票", "locale": ["zh_CN"]}},
    "content_variant": {"id": "v1", "angle": "早鸟", "headline": "H1", "summary": "S1"},
    "send_conditions": {"delay_hours": 48, "max_per_24h": 2, "max_per_7d": 5},
    "tags_to_write": ["wave_old"],
    "discount": {"enabled": True, "pct": 5, "note": "早鸟 5%"},
    "judgment": "进入：打开>=1",
}
s5 = normalize_campaign(OLD_C, 0, goal_id="g")
missing = [k for k in OLD_KEYS if k not in s5]
check(not missing, f"旧键全部保留（缺：{missing}）")
check(s5["cid"] == "old_c1" and s5["wave_id"] == "wave_1" and s5["segment"] == "SEG_OLD",
      "身份/分群字段不变")
check(s5["email_ref"] == "EM_OLD" and s5["subject"] == "老主题", "邮件字段不变")
check(s5["content_variant"] == 1 and s5["content_variant_spec"]["angle"] == "早鸟",
      "content_variant 不变")
sc5 = s5["send_conditions"]
check(sc5["delay_hours"] == 48 and sc5["max_per_24h"] == 2 and sc5["max_per_7d"] == 5,
      "显式 send_conditions 原样生效（画像包不覆盖）")
check(s5["tags_to_write"] == ["wave_old"] and s5["discount"]["pct"] == 5, "tag / 折扣不变")
check(s5["judgment"] == "进入：打开>=1" and s5["journey"] == "promo", "judgment / journey 不变")
check(s5["branches"] == [] and s5["stage_rules"] == [], "老 spec 无分叉 → 空列表（不发明分支）")
check(s5["window"] is None, "老 spec 无周期 → None")
check(all(k in s5 for k in NEW_KEYS), f"新键全部存在（{NEW_KEYS}）")
# 老 spec 唯一变化点：quiet_hours 由 GENERIC 画像包补齐（画像包默认值首次真正生效）
gen = audience_map.send_defaults("GENERIC")
check(sc5["quiet_hours"] == gen["quiet_hours"],
      f"quiet_hours 未显式 → 取 GENERIC 画像包默认（{gen['quiet_hours']}）")

print("\n=== 6. 优先级：红线 > 规格 > 画像包 > 常量 ===")
PKG = "HNW_FAMILY"
pkg_qh = audience_map.send_defaults(PKG)["quiet_hours"]
pkg_7d = audience_map.send_defaults(PKG)["max_per_7d"]
check(pkg_7d != S.DEFAULT_SEND_CONDITIONS["max_per_7d"],
      f"画像包 max_per_7d({pkg_7d}) 与常量缺省({S.DEFAULT_SEND_CONDITIONS['max_per_7d']}) 不同（便于断言来源）")

# 6a 画像包默认生效
s6a = compose_final_strategy({"audience_package": PKG, "campaigns": [{"cid": "p1"}]})[0]
check(s6a["send_conditions"]["max_per_7d"] == pkg_7d, "无显式值 → 画像包频次生效")
check(s6a["send_conditions"]["quiet_hours"] == pkg_qh, "无显式值 → 画像包静默窗生效")
check(s6a["_compose"]["package"] == PKG, "_compose.package = 画像包 code")
check("max_per_7d" in s6a["_compose"]["from_package"], "溯源：max_per_7d 来自 package")

# 6b 规格显式值 > 画像包
s6b = compose_final_strategy(
    {"audience_package": PKG,
     "campaigns": [{"cid": "p2", "send_conditions": {"max_per_7d": 9,
                                                     "quiet_hours": "23:00-08:00"}}]})[0]
check(s6b["send_conditions"]["max_per_7d"] == 9, "规格显式 max_per_7d 覆盖画像包")
check(s6b["send_conditions"]["quiet_hours"] == "23:00-08:00", "规格显式 quiet_hours 覆盖画像包")
check("max_per_7d" in s6b["_compose"]["from_spec"], "溯源：max_per_7d 来自 spec")

# 6c 红线 > 规格 > 画像包
s6c = compose_final_strategy(
    {"audience_package": PKG,
     "campaigns": [{"cid": "p3", "send_conditions": {"quiet_hours": "23:00-08:00"}}]},
    constraints=["20:00~00:00免打扰"])[0]
check(s6c["send_conditions"]["quiet_hours"] == "20:00-00:00",
      f"红线静默窗最高优先级（得到 {s6c['send_conditions']['quiet_hours']}）")
check("quiet_hours" in s6c["_compose"]["from_constraints"], "溯源：quiet_hours 来自 red_line")
check(parse_quiet_hours(["20:00~00:00免打扰"]) == "20:00-00:00",
      "parse_quiet_hours 仍是确定性红线解析")

# 6d goal 属性作为画像包来源
class _G:
    audience_package = PKG
    audience_segment = "SEG_G"
    goal_id = "g_goal"
    meta = {"constraints": ["20:00~00:00免打扰"]}


s6d = compose_final_strategy({"campaigns": [{"cid": "p4"}]}, _G())[0]
check(s6d["_compose"]["package"] == PKG, "goal.audience_package 作为画像包来源")
check(s6d["send_conditions"]["quiet_hours"] == "20:00-00:00",
      "goal.meta.constraints 派生红线（strategies_from_spec 行为不变）")
check(s6d["segment"] == "SEG_G", "goal.audience_segment 仍是缺省分群")

print("\n=== 7. 画像包富化：内容 / 视觉 / CTA ===")
s7 = compose_final_strategy({"audience_package": PKG, "campaigns": [{"cid": "q1"}]})[0]
check(s7["content_direction"] == audience_map.content_direction(PKG),
      "content_direction = 画像包文案方向")
check(s7["visual_direction"] == audience_map.visual_direction(PKG),
      "visual_direction = 画像包落地页视觉方向")
check(s7["cta_templates"] == audience_map.content_direction(PKG)["cta_templates"],
      f"cta_templates = 画像包 CTA 模板（{s7['cta_templates']}）")
s7b = compose_final_strategy(
    {"audience_package": PKG,
     "campaigns": [{"cid": "q2", "cta_templates": ["立即报名"]}]})[0]
check(s7b["cta_templates"] == ["立即报名"], "规格显式 cta_templates 覆盖画像包")
check("cta_templates" in s7b["_compose"]["from_spec"], "溯源：cta_templates 来自 spec")

print("\n=== 8. 活动周期 window / 节奏 cadence_days ===")
s8 = compose_final_strategy(
    {"window": {"start": "2028-05-01", "end": "2028-07-09"},
     "campaigns": [{"cid": "w1"},
                   {"cid": "w2", "window": {"start": "2028-06-01", "end": "2028-06-30"}}]})
check(s8[0]["window"] == {"start": "2028-05-01", "end": "2028-07-09"},
      "campaign 无 window → 回落 spec 层周期")
check(s8[1]["window"] == {"start": "2028-06-01", "end": "2028-06-30"},
      "campaign 自带 window 优先")
s8b = compose_final_strategy(
    {"campaigns": [{"cid": "w3", "send_conditions": {"cadence_days": 7}}]})[0]
check(s8b["send_conditions"]["cadence_days"] == 7, "cadence_days 存下来（不再被忽略）")
check(s8b["send_conditions"]["delay_hours"] == 168, "cadence_days=7 → delay_hours=168")
s8c = compose_final_strategy(
    {"campaigns": [{"cid": "w4", "send_conditions": {"cadence_days": 7, "delay_hours": 12}}]})[0]
check(s8c["send_conditions"]["delay_hours"] == 12, "显式 delay_hours 优先于 cadence_days 折算")

print("\n=== 9. strategies_from_spec 与 compose_final_strategy 同构 ===")
SPEC9 = {"goal_id": "g9", "audience_package": PKG,
         "campaigns": [{"cid": "z1", "branches": [{"id": "b1", "when": "email.click"}]}]}
a = strategies_from_spec(SPEC9)
b = compose_final_strategy(SPEC9)
check([x["cid"] for x in a] == [x["cid"] for x in b] == ["z1"], "两者返回同构列表")
check(a[0]["_compose"]["package"] == PKG, "strategies_from_spec 也带画像包溯源")
check(len(a[0]["branches"]) == 1, "strategies_from_spec 也解析分叉")
check(json.dumps(a, ensure_ascii=False, sort_keys=True) ==
      json.dumps(b, ensure_ascii=False, sort_keys=True), "两条通路输出完全一致")

print("\n=== 汇总 ===")
if fails:
    print(f"\n❌ {len(fails)} 项失败：")
    for f in fails:
        print("  - " + f)
    raise SystemExit(1)
print("\n✅ 全部通过（分叉 / 条件 / 终点 / 阶段升降级 / 主流程终点 / 画像包+规格+属性 合并优先级）")
