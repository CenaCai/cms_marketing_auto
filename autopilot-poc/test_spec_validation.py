"""
test_spec_validation.py — spec_validation 纯单元测试（不依赖活服务 / 不依赖 Mautic）
=====================================================================
验证：StrategySpec 与 /brief 基础信息冲突时，validate_spec 能逐项列出冲突，
      且任何缺失/畸形输入都不抛异常。

运行：python test_spec_validation.py   （全绿退出码 0，有失败退出码 1）
"""
import os
import sys

from spec_validation import (Conflict, validate_spec, format_conflicts,
                             parse_frequency_caps)

OK = [True]


def check(name, cond, extra=""):
    print(("✅" if cond else "❌"), name, extra)
    if not cond:
        OK[0] = False


def fields(cs):
    return [c.field for c in cs]


# ------------------------------------------------------- 基线：一份「一致」的 Brief
BRIEF = {
    "objective": "UCL2028 门票预售",
    "goal_name": "UCL2028 预售",
    "start_date": "2028-05-01",
    "end_date": "2028-07-09",
    "overall_conv": "0.15",
    "locale": ["zh_CN"],
    "constraints": "20:00~00:00免打扰\n每周≤3封\n每天≤1封",
    "audience_region": ["中国大陆"],
    "audience_profile": {"region": ["中国大陆"]},
    "is_revenue": True,
    "budget": "0",
}

OK_SPEC = {
    "goal_id": "ucl2028",
    "audience_package": "YOUNG_TREND",
    "locale": ["zh_CN"],
    "window": {"start": "2028-05-01", "end": "2028-07-09"},
    "kpi": {"metric": "conversion", "target": 0.15},
    "campaigns": [
        {"cid": "c1", "send_conditions": {"quiet_hours": "20:00-00:00",
                                          "max_per_7d": 3, "max_per_24h": 1}},
        {"cid": "c2", "send_conditions": {"quiet_hours": "20:00~00:00",
                                          "max_per_7d": 2, "max_per_24h": 1}},
    ],
}

# ---------------------------------------------------------------- (a) 一致 → 0
cs = validate_spec(OK_SPEC, BRIEF, "YOUNG_TREND")
check("(a) 一致 spec → 0 冲突", len(cs) == 0, f"got={fields(cs)}")

# ------------------------------------------------------------ (b) locale 不匹配
bad = dict(OK_SPEC, locale=["en_US"])
cs = validate_spec(bad, BRIEF, "YOUNG_TREND")
check("(b1) locale 不匹配 → 1 冲突", len(cs) == 1 and cs[0].field == "locale",
      f"got={fields(cs)}")
check("(b2) locale 冲突文案含两侧取值",
      bool(cs) and "en_US" in cs[0].message and "zh_CN" in cs[0].message,
      cs[0].message if cs else "")
# 部分重叠（zh_CN+en_US vs zh_CN）不算冲突
cs = validate_spec(dict(OK_SPEC, locale=["en_US", "zh_CN"]), BRIEF, "YOUNG_TREND")
check("(b3) locale 有交集 → 0 冲突", len(cs) == 0, f"got={fields(cs)}")
# 任一侧缺失 → 跳过
cs = validate_spec({k: v for k, v in OK_SPEC.items() if k != "locale"}, BRIEF, None)
check("(b4) spec 无 locale → 跳过", len(cs) == 0, f"got={fields(cs)}")
cs = validate_spec(OK_SPEC, {k: v for k, v in BRIEF.items() if k != "locale"}, None)
check("(b5) brief 无 locale → 跳过", len(cs) == 0, f"got={fields(cs)}")

# --------------------------------------------------- (c) audience_package 不匹配
cs = validate_spec(OK_SPEC, BRIEF, "FAMILY_EDU")
check("(c1) audience_package 不匹配 → 1", len(cs) == 1 and cs[0].field == "audience_package",
      f"got={fields(cs)}")
check("(c2) 冲突文案点名两侧包", bool(cs) and "YOUNG_TREND" in cs[0].message
      and "FAMILY_EDU" in cs[0].message, cs[0].message if cs else "")
cs = validate_spec(OK_SPEC, BRIEF, "young_trend")   # 大小写/空格差异不算冲突
check("(c3) audience_package 大小写不敏感 → 0", len(cs) == 0, f"got={fields(cs)}")
cs = validate_spec(OK_SPEC, BRIEF, None)            # 服务端没推断出包 → 跳过
check("(c4) pkg_code 为 None → 跳过", len(cs) == 0, f"got={fields(cs)}")

# ------------------------------------------------------ (d) quiet_hours 红线
bad = {
    "locale": ["zh_CN"],
    "campaigns": [
        {"cid": "c1", "send_conditions": {"quiet_hours": "20:00-09:00"}},  # 午夜被吃掉
        {"cid": "c2", "send_conditions": {"quiet_hours": "20:00~00:00"}},  # 波形线写法，OK
        {"cid": "c3", "send_conditions": {}},                              # 缺失
    ],
}
cs = validate_spec(bad, BRIEF, None)
check("(d1) quiet_hours 不匹配/缺失 → 每个违规 campaign 1 条",
      len(cs) == 2 and fields(cs) == ["quiet_hours", "quiet_hours"], f"got={fields(cs)}")
check("(d2) 只报违规 campaign（c1/c3）",
      [c.campaign for c in cs] == ["c1", "c3"], f"got={[c.campaign for c in cs]}")
check("(d3) 缺失时的 spec_value 有占位",
      any(c.campaign == "c3" and "未设置" in c.spec_value for c in cs))
# 约束没写免打扰 → 该规则不触发
no_qh = {k: v for k, v in BRIEF.items() if k != "constraints"}
cs = validate_spec(bad, dict(no_qh, constraints="每周≤3封"), None)
check("(d4) 约束无免打扰 → 不校验 quiet_hours", len(cs) == 0, f"got={fields(cs)}")

# ------------------------------------------------------ (e) 频次硬顶
bad = {"locale": ["zh_CN"],
       "campaigns": [{"cid": "c1", "send_conditions": {"quiet_hours": "20:00-00:00",
                                                       "max_per_7d": 5, "max_per_24h": 1}}]}
cs = validate_spec(bad, BRIEF, None)
check("(e1) max_per_7d=5 vs 每周≤3封 → 1", len(cs) == 1 and cs[0].field == "max_per_7d",
      f"got={fields(cs)}")
check("(e2) 频次冲突带 cid", bool(cs) and cs[0].campaign == "c1")
bad2 = {"locale": ["zh_CN"],
        "campaigns": [{"cid": "c1", "send_conditions": {"quiet_hours": "20:00-00:00",
                                                        "max_per_7d": 3, "max_per_24h": 2}}]}
cs = validate_spec(bad2, BRIEF, None)
check("(e3) max_per_24h=2 vs 每天≤1封 → 1", len(cs) == 1 and cs[0].field == "max_per_24h",
      f"got={fields(cs)}")
cs = validate_spec(bad2, dict(BRIEF, constraints="每周≤3封"), None)  # 只有周约束
check("(e4) 约束只有每周 → 不校验每天", len(cs) == 0, f"got={fields(cs)}")
check("(e5) 解析「每周≤3封」", parse_frequency_caps("每周≤3封")[0] == 3.0)
check("(e6) 解析「每周不超过3封」", parse_frequency_caps("每周不超过3封")[0] == 3.0)
check("(e7) 解析「每周<=3」", parse_frequency_caps("每周<=3")[0] == 3.0)
check("(e8) 解析「每天≤1封」", parse_frequency_caps("每天≤1封")[1] == 1.0)
check("(e9) 无频次约束 → (None, None)", parse_frequency_caps("仅一条普通约束") == (None, None))

# ------------------------------------------------------ (f) 投放窗口
cs = validate_spec(dict(OK_SPEC, window={"start": "2028-04-01", "end": "2028-07-09"}),
                   BRIEF, None)
check("(f1) window 早于 Brief 开始日 → 1", len(cs) == 1 and cs[0].field == "window_start",
      f"got={fields(cs)}")
cs = validate_spec(dict(OK_SPEC, window={"start": "2028-05-01", "end": "2028-08-01"}),
                   BRIEF, None)
check("(f2) window 晚于 Brief 结束日 → 1", len(cs) == 1 and cs[0].field == "window_end",
      f"got={fields(cs)}")
cs = validate_spec(dict(OK_SPEC, window={"start": "2028-07-09", "end": "2028-05-01"}),
                   BRIEF, None)
check("(f3) window 开始晚于结束（自洽检查）→ 1",
      len(cs) == 1 and cs[0].field == "window_order", f"got={fields(cs)}")
cs = validate_spec(dict(OK_SPEC, window={"start": "2028-06-01", "end": "2028-06-30"}),
                   {k: v for k, v in BRIEF.items() if k not in ("start_date", "end_date")},
                   None)
check("(f4) Brief 无日期 → 只做自洽检查 → 0", len(cs) == 0, f"got={fields(cs)}")

# ------------------------------------------------------ (g) 地区 vs zh_CN
hk = dict(BRIEF, audience_region=["中国香港"], audience_profile={"region": ["中国香港"]})
cs = validate_spec(OK_SPEC, hk, None)
check("(g1) 地区不含中国大陆 + locale 含 zh_CN → 1",
      len(cs) == 1 and cs[0].field == "region_locale", f"got={fields(cs)}")
hk2 = dict(hk, locale=["en_US"])
cs = validate_spec(dict(OK_SPEC, locale=["en_US"]), hk2, None)
check("(g2) 地区不含中国大陆 + locale 无 zh_CN → 0", len(cs) == 0, f"got={fields(cs)}")
cs = validate_spec(OK_SPEC, BRIEF, None)
check("(g3) 地区含中国大陆 + zh_CN → 0", len(cs) == 0, f"got={fields(cs)}")
# audience_profile.region 也能作为地区来源（不依赖 audience_region 键）
cs = validate_spec(OK_SPEC, {k: v for k, v in hk.items() if k != "audience_region"}, None)
check("(g4) 地区取自 audience_profile.region", len(cs) == 1 and cs[0].field == "region_locale",
      f"got={fields(cs)}")

# ------------------------------------------------------ (h) KPI 目标
cs = validate_spec(dict(OK_SPEC, kpi={"target": 0.15}), dict(BRIEF, overall_conv="0.20"), None)
check("(h1) kpi 0.15 vs overall_conv 0.20 → 1",
      len(cs) == 1 and cs[0].field == "kpi_target", f"got={fields(cs)}")
cs = validate_spec(dict(OK_SPEC, kpi={"target": 0.15}), dict(BRIEF, overall_conv="0.15"), None)
check("(h2) kpi 与 overall_conv 相同 → 0", len(cs) == 0, f"got={fields(cs)}")
cs = validate_spec(dict(OK_SPEC, kpi={"target": 0.15}), dict(BRIEF, overall_conv=""), None)
check("(h3) overall_conv 留空 → 跳过", len(cs) == 0, f"got={fields(cs)}")
cs = validate_spec(dict(OK_SPEC, kpi={"target": None}), BRIEF, None)
check("(h4) kpi target 为 None → 跳过", len(cs) == 0, f"got={fields(cs)}")

# ------------------------------------------------------ (i) 空 spec → 0，不抛异常
try:
    cs = validate_spec({}, BRIEF, "YOUNG_TREND")
    check("(i1) 空 spec → 0 冲突", len(cs) == 0, f"got={fields(cs)}")
except Exception as e:
    check("(i1) 空 spec → 0 冲突", False, f"抛异常 {type(e).__name__}: {e}")
try:
    cs = validate_spec({}, {}, None)
    check("(i2) 空 spec + 空 brief → 0 冲突", len(cs) == 0, f"got={fields(cs)}")
except Exception as e:
    check("(i2) 空 spec + 空 brief → 0 冲突", False, f"抛异常 {type(e).__name__}: {e}")

# ------------------------------------------------------ (j) 畸形 spec 不抛异常
MALFORMED = {
    "campaigns": "这不是列表",          # campaigns 是字符串
    "kpi": None,                        # kpi 为 None
    "window": "2028-05-01",             # window 是字符串
    "locale": 12345,                    # locale 是数字
    "audience_package": {"a": 1},       # 包是 dict
}
try:
    cs = validate_spec(MALFORMED, BRIEF, "YOUNG_TREND")
    check("(j1) 畸形 spec 不抛异常", True, f"conflicts={fields(cs)}")
except Exception as e:
    check("(j1) 畸形 spec 不抛异常", False, f"{type(e).__name__}: {e}")

MALFORMED2 = {"campaigns": [None, "x", {"cid": "c9", "send_conditions": None}]}
try:
    cs = validate_spec(MALFORMED2, BRIEF, None)
    qh = [c for c in cs if c.field == "quiet_hours"]
    check("(j2) send_conditions 为 None → 报「未设置」",
          len(qh) == 1 and qh[0].campaign == "c9", f"got={[c.campaign for c in qh]}")
except Exception as e:
    check("(j2) send_conditions 为 None → 报「未设置」", False, f"{type(e).__name__}: {e}")

try:
    cs = validate_spec(OK_SPEC, {"constraints": None, "locale": None}, None)
    check("(j3) brief 字段为 None → 不抛异常", isinstance(cs, list), f"n={len(cs)}")
except Exception as e:
    check("(j3) brief 字段为 None → 不抛异常", False, f"{type(e).__name__}: {e}")

# ------------------------------------------------------ format_conflicts
check("(k1) format_conflicts([]) == []", format_conflicts([]) == [])
check("(k2) format_conflicts(None) 也安全", format_conflicts(None) == [])

multi = validate_spec(
    {"locale": ["en_US"], "audience_package": "PKG_X",
     "campaigns": [{"cid": "c1", "send_conditions": {"quiet_hours": "20:00-09:00",
                                                     "max_per_7d": 5, "max_per_24h": 1}}]},
    BRIEF, "YOUNG_TREND")
lines = format_conflicts(multi)
check("(k3) 4 条冲突 → 4 行", len(lines) == 4, f"n={len(lines)} fields={fields(multi)}")
check("(k4) 每行以 · 开头", all(l.startswith("· ") for l in lines))
check("(k5) 逐 campaign 的行带（cid）",
      any(("（c1）" in l) for l in lines), lines[0] if lines else "")
if "--demo" in sys.argv:
    print("\n---- 一次违反 4 条规则的 format_conflicts 输出 ----")
    for l in lines:
        print(l)

# ------------------------------------------------------ severity / 数据结构
check("(k6) 全部 severity=block", all(c.severity == "block" for c in multi))
check("(k7) Conflict 是 dataclass 且字段完整",
      isinstance(multi[0], Conflict)
      and set(("field", "spec_value", "brief_value", "message", "campaign", "severity"))
      <= set(Conflict.__dataclass_fields__))
check("(k8) field 为稳定机器键",
      {"locale", "audience_package", "quiet_hours", "max_per_7d"} <= set(fields(multi)))

print("\nRESULT:", "ALL PASS" if OK[0] else "FAILED")
sys.exit(0 if OK[0] else 1)
