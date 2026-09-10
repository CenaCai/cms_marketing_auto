"""
test_refactor.py — 验证「基础路径拓扑模板 + 完整策略修正」重构
三层模型：
  L1 拓扑模板（topology.py）       —— 核心流程形状，无内容
  L2 策略由意图+StrategySpec 实例化  —— N 来自 spec；未提交时回落拓扑缺省单 campaign
  L3 evaluate_and_replan 修订完整策略 —— 频次/内容/折扣/受众/分支 五维
"""
from __future__ import annotations
import json
from goal_intake import parse_brief
from strategy_spec import strategies_from_spec
from adaptive import build_program, evaluate_and_replan, topology_default_strategy, default_strategies
from plan_compiler import compile
from topology import TOPOLOGIES, journey_for_intent, journey_stages

GOAL = parse_brief({
    "goal_id": "refactor_demo",
    "objective": "UCL2028 决赛门票促销",
    "kpi": {"type": "conversion_rate", "target": 0.15},
    "audience_segment": "SEG_UCL_FANS",
    "landing_page_url": "",
})

SPEC = {
    "goal_id": "refactor_demo",
    "objective": "UCL2028 决赛门票促销",
    "kpi": {"metric": "conversion", "target": 0.15},
    "campaigns": [
        {
            "cid": "refactor_demo_c1", "name": "首波·早鸟",
            "segment": {"mode": "reuse", "ref": "SEG_UCL_FANS"},
            "email": {"mode": "reuse", "ref": "EM_EARLY",
                      "brief": {"subject": "早鸟开抢", "angle": "权益", "cta": "购票", "locale": []}},
            "content_variant": {"id": "v1", "angle": "早鸟", "headline": "H1", "summary": "S1"},
            "send_conditions": {"delay_hours": 0, "max_per_24h": 2, "max_per_7d": 5},
            "discount": {"enabled": True, "pct": 5, "note": "早鸟 5%"},
            "tags_to_write": ["wave_early"],
        },
        {
            "cid": "refactor_demo_c2", "name": "次波·提醒",
            "segment": {"mode": "reuse", "ref": "SEG_UCL_FANS"},
            "email": {"mode": "reuse", "ref": "EM_REMIND",
                      "brief": {"subject": "最后机会", "angle": "紧迫", "cta": "购票", "locale": []}},
            "content_variant": {"id": "v2", "angle": "提醒", "headline": "H2", "summary": "S2"},
            "send_conditions": {"delay_hours": 48, "max_per_24h": 1, "max_per_7d": 3},
            "discount": {"enabled": True, "pct": 5, "note": "次波 5%"},
            "tags_to_write": ["wave_remind"],
        },
    ],
}

fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        fails.append(msg)


print("\n=== L1 拓扑模板 ===")
check(journey_for_intent("promo") == "promo", "promo → PROMO_JOURNEY")
check(journey_for_intent("service") == "service", "service → SERVICE_JOURNEY")
check("branch.engaged" in TOPOLOGIES["promo"]["branches"], "PROMO 拓扑含点击分支锚点")
check(len(journey_stages("promo")) == 11, "PROMO 拓扑 11 个阶段")

print("\n=== L2 策略由意图+StrategySpec 实例化 ===")
strategies = strategies_from_spec(SPEC, GOAL)
check(len(strategies) == 2, "StrategySpec 派生 2 个 campaign（N 来自 spec，非硬编码）")
check(strategies[0]["journey"] == "promo", "campaign 带 journey=promo")
check(strategies[0]["discount"] == {"enabled": True, "pct": 5, "note": "早鸟 5%"},
      "discount 透传（策略本体：早鸟 5%）")

prog = build_program(GOAL, strategy_spec=strategies)
check(prog["n_campaigns"] == 2, "build_program 用 spec → 2 campaign")
check(prog["strategy_source"] == "agent_spec", "strategy_source=agent_spec")

# compile 把折扣反映进邮件主题
p1 = compile(GOAL, strategies[0])
subj = p1["campaign"]["strategy"].get("subject", "")
check("OFF" in subj, f"compile 折扣反映进主题（{subj!r}）")
# 折扣区（无折扣的 campaign 不应被加 OFF）
p2n = compile(GOAL, topology_default_strategy(GOAL))
check("OFF" not in p2n["campaign"]["strategy"].get("subject", ""), "无折扣 campaign 主题不加 OFF")
check(p1["strategy_ref"].get("discount", {}).get("pct") == 5, "compile strategy_ref 带 discount")

print("\n=== L2 未提交 StrategySpec → 拓扑缺省单 campaign（不发明波次）===")
def_strat = topology_default_strategy(GOAL)
check(isinstance(def_strat, dict) and def_strat["cid"].endswith("_c1"), "拓扑缺省 = 单 campaign")
check(def_strat["strategy_source"] == "topology_default", "strategy_source=topology_default")
check(def_strat["send_conditions"]["delay_hours"] == 24, "缺省 delay 24h（非 24*(i+1) 递进）")
check(def_strat.get("discount") is None, "缺省无折扣（不编造）")
# default_strategies 别名向后兼容
alias = default_strategies(GOAL, 3)
check(isinstance(alias, list) and len(alias) == 1, "default_strategies 别名返回单 campaign 列表")
prog_def = build_program(GOAL)  # 无 spec
check(prog_def["n_campaigns"] == 1, "无 spec → build_program 仅 1 campaign（不再 3 波递进）")

print("\n=== L3 evaluate_and_replan 修订完整策略（weak：乏力）===")
prog2 = build_program(GOAL, strategy_spec=strategies_from_spec(SPEC, GOAL))
res = evaluate_and_replan(prog2, "refactor_demo_c1", {"conversion": 0.05, "unsub": 0.001})
# ratio = 0.05/0.15 = 0.33 < 0.5 → weak
check(res["verdict"] == "weak", f"verdict=weak（ratio={res['ratio']}）")
c2 = next(c for c in prog2["campaigns"] if c["cid"] == "refactor_demo_c2")
check(c2["strategy"]["send_conditions"]["max_per_24h"] == 1 + 2, "下游 c2 频次 +2（乏力大幅提频）")
check("broaden" in c2["strategy"]["tags_to_write"], "下游 c2 加 broaden 分组 tag")
check(c2["strategy"].get("segment_broaden") is True, "下游 c2 标记 segment_broaden（受众轴）")
check(c2["strategy"].get("discount", {}).get("enabled") is True, "下游 c2 开启折扣挽回（折扣轴）")
check(c2["strategy"]["discount"]["pct"] == 10, "下游 c2 折扣 10%（未设→开启）")
check(c2["strategy"]["email_brief"]["angle"] == "折扣挽回", "下游 c2 邮件角度转折扣挽回（内容轴）")
check(len(res["new_campaigns"]) == 1, "新增 1 条折扣挽回分支 campaign（分支轴）")
branch = res["new_campaigns"][0]
check(branch["cid"] == "refactor_demo_reengage_refactor_demo_c1", "分支 campaign cid 正确")
added = next(c for c in prog2["campaigns"] if c["cid"] == branch["cid"])
check(added["status"] == "unreviewed", "新增分支 campaign 状态 unreviewed（待审批）")
check(added["strategy"]["discount"]["pct"] == 10, "分支 campaign 折扣 10%")
check(prog2["n_campaigns"] == 3, "program 现含 3 campaign（原 2 + 分支 1）")

print("\n=== L3 退订熔断（burn）===")
prog3 = build_program(GOAL, strategy_spec=strategies_from_spec(SPEC, GOAL))
res3 = evaluate_and_replan(prog3, "refactor_demo_c1", {"conversion": 0.2, "unsub": 0.005})
check(res3["verdict"] == "burn", "verdict=burn（退订 0.5%>0.3%）")
c2b = next(c for c in prog3["campaigns"] if c["cid"] == "refactor_demo_c2")
check(c2b["strategy"]["send_conditions"]["max_per_24h"] == 2 - 1, "下游 c2 降频（2→1）")
check("suppressed" in c2b["strategy"]["tags_to_write"], "下游 c2 加 suppressed 收窄 tag")
# c1 原本折扣 5% → 退守至 2%（5//2）
check(c2b["strategy"]["discount"]["pct"] == 2, "下游 c2 折扣退守 5%→2%")
check(c2b["strategy"]["email_brief"]["angle"] == "价值导向（非促销）", "下游 c2 软化内容角度")

print("\n=== L3 达标剪枝分支（strong + prune）===")
prog4 = build_program(GOAL, strategy_spec=strategies_from_spec(SPEC, GOAL))
# 手工挂一条 deferred 兜底分支（tag 标记来自 c2）
prog4["campaigns"].append({
    "cid": "refactor_demo_fallback_c2", "wave_id": "wave_fb",
    "strategy": {"cid": "refactor_demo_fallback_c2", "tags_to_write": ["branch_of_refactor_demo_c2"],
                 "send_conditions": {"max_per_24h": 1}},
    "proposal": {}, "status": "deferred", "result": None,
})
res4 = evaluate_and_replan(prog4, "refactor_demo_c2", {"conversion": 0.18, "unsub": 0.001})
check(res4["verdict"] == "strong", f"verdict=strong（ratio={res4['ratio']}）")
pruned = [c for c in prog4["campaigns"] if c["cid"] == "refactor_demo_fallback_c2"][0]
check(pruned["status"] == "done_met", "达标 → 剪掉挂起兜底分支（status=done_met）")
check(any(p["cid"] == "refactor_demo_fallback_c2" for p in res4["pruned_campaigns"]), "pruned_campaigns 记录剪枝")

print("\n=== 汇总 ===")
if fails:
    print(f"\n❌ {len(fails)} 项失败：")
    for f in fails:
        print("  - " + f)
    raise SystemExit(1)
print("\n✅ 全部通过（L1 拓扑模板 / L2 意图+spec 实例化 / L3 五维完整策略修正）")
