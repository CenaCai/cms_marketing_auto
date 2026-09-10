"""
test_branch_compile.py — 验证「StrategySpec 真正驱动事件图」
=====================================================================
覆盖 plan_compiler 消费策略规格声明的：
  1. branches：分叉数量 = 声明数量，判断条件来自 condition.signal，顺序/id 保留
  2. endpoint：tags / stage / segment / email / landing_page / form → 对应终点节点
  3. stage_rules：阶段升降级节点带 when 条件与 direction（审计可查）
  4. main_endpoint：主流程终点 + 终点判断（judgment），terminal 收口
  5. window：活动周期约束/标注
  6. 老 spec 回归：无 branches → 事件图节点序列与改动前完全一致
  7. Mautic 事件图不变量：newN / anchors.target='top' / yes-no-bottom-leadsource / 无悬空连线

纯标准库，无需服务；与 test_branches.py 同款 check() 风格。
"""
from __future__ import annotations

import json
import re

from goal_intake import parse_brief
from plan_compiler import (GENERIC_DECISION_TYPE, _MAUTIC_TYPE, compile,
                           to_mautic_events)
from strategy_spec import compose_final_strategy

GOAL = parse_brief({
    "goal_id": "ucl2028",
    "objective": "邀请 2028 欧超决赛意向客户登记",
    "kpi": {"type": "conversion_rate", "target": 0.15},
    "audience_segment": "SEG_UCL_FANS",
    "landing_page_url": "http://localhost:8080/s/ucl-lp",
})

fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        fails.append(msg)


def strat(campaign: dict, **spec_top) -> dict:
    """一个 campaign 的 spec → 归一化后的 strategy dict（走真实归一化通路）。

    默认 asset_resolve=False：单测不碰 Mautic（资产解析有专门的注入用例），
    这样「终点节点长什么样」的断言不会被本机 Mautic 上有没有同名资产所左右。
    """
    spec = dict(spec_top)
    spec["campaigns"] = [campaign]
    s = compose_final_strategy(spec, GOAL)[0]
    s.setdefault("asset_resolve", False)
    return s


def by_id(graph):
    return {n["id"]: n for n in graph}


def types_of(graph):
    return [n["type"] for n in graph]


# ---------------------------------------------------------------- 不变量校验
def check_invariants(p, label):
    """Mautic 7 事件图不变量（任一处破坏都会导致 setEvents/setCanvasSettings 500）。"""
    events = p["mautic_events"]
    canvas = p["mautic_canvas"]
    eids = {e["id"] for e in events}
    nids = {n["id"] for n in canvas["nodes"]}
    check(len(eids) == len(events), f"{label}：事件 id 唯一（无重复 newN）")
    check(all(re.fullmatch(r"new\d+", e["id"]) for e in events),
          f"{label}：事件 id 形如 newN")
    check(eids == nids, f"{label}：canvasSettings.nodes 与 events 一一对应")
    check(all(e.get("eventType") in ("action", "decision", "condition") for e in events),
          f"{label}：每个事件都带 eventType")
    check(all(c["anchors"].get("target") == "top" for c in canvas["connections"]),
          f"{label}：所有连线 anchors.target='top'（非 top 会触发 Mautic 7 内部 500）")
    bad_src = [c for c in canvas["connections"]
               if c["anchors"].get("source") not in ("yes", "no", "bottom", "leadsource")]
    check(not bad_src, f"{label}：连线 anchors.source ∈ yes/no/bottom/leadsource（越界：{bad_src}）")
    # 悬空端点：source/target 必须落在「事件 id」或 lead source 上
    dangling = [c for c in canvas["connections"]
                if c["sourceId"] not in eids | {"lists"} or c["targetId"] not in eids]
    check(not dangling, f"{label}：无悬空连线（悬空：{dangling}）")
    # 决策分支锚点必须是 yes/no
    for c in canvas["connections"]:
        if c["anchors"].get("source") in ("yes", "no"):
            src = next((e for e in events if e["id"] == c["sourceId"]), None)
            check(src is not None and src["eventType"] == "decision",
                  f"{label}：yes/no 连线的来源必须是 decision 事件（{c['sourceId']}）")
    return events, canvas


print("\n=== a. 1 个分叉 → 1 个决策节点 + 分支终点节点 ===")
S1 = strat({
    "cid": "c1", "name": "首波",
    "segment": {"mode": "reuse", "ref": "SEG_UCL_FANS"},
    "email": {"mode": "reuse", "ref": "EM_A", "brief": {"subject": "早鸟开抢"}},
    "branches": [
        {"id": "clicked",
         "condition": {"signal": "email.click", "op": ">=", "value": 1},
         "endpoint": {"tags": ["clicked"], "stage": "engaged"}},
    ],
})
p1 = compile(GOAL, S1)
g1 = by_id(p1["graph"])
check("n_fork_clicked" in g1, "分叉节点按 branch id 命名（n_fork_clicked）")
check(g1.get("n_fork_clicked", {}).get("type") == "decision.clicked",
      "email.click → decision.clicked（复用已有点击决策）")
fp = g1["n_fork_clicked"]["params"]
check(fp.get("signal") == "email.click" and fp.get("op") == ">=" and fp.get("value") == 1,
      f"判断条件来自 spec（{fp.get('signal')} {fp.get('op')} {fp.get('value')}）")
check(fp.get("if_true") == "n_fork_clicked_tag", "命中 → 该分支第一个终点节点")
check(fp.get("if_false") == "n_tag", "未命中 → 汇入主流程（n_tag）")
check(g1.get("n_fork_clicked_tag", {}).get("type") == "tag.write", "终点 tags → tag.write 节点")
check(g1.get("n_fork_clicked_tag", {}).get("params", {}).get("tags") == ["clicked"],
      "终点 tag 内容来自 spec")
# 关键语义：声明了 tags + stage 两个字段 ≠ 触发两个动作。
# email.click 的语义优先级是「落地页 → 表单 → 邮件 → 打标 → 分组 → 阶段」，
# 本分支没声明落地页/表单/邮件，故判定为只打标。
check("n_fork_clicked_stage" not in g1,
      "声明了 stage 但判定只触发打标 → 不生成 stage 节点（不是三类都触发）")
check(len([n for n in p1["graph"] if n["id"].startswith("n_fork_clicked_")]) == 1,
      "一个分支只出 1 个终点动作节点")
check(any("只触发" in w and "忽略" in w for w in p1.get("compile_warnings", [])),
      f"推断只触发一个 → 记 compile_warning 说明忽略了什么（{p1.get('compile_warnings')}）")
check(g1["n_fork_clicked_tag"].get("next") == "n_tag",
      "非 terminal 分支 → 汇入公共落库（n_tag）")
check("n_branch" not in g1 and "n_lp" not in g1 and "n_followup" not in g1,
      "声明了分叉 → 不再套用模板里的硬编码点击分支（分叉数 = 声明数）")

print("\n=== a2. 显式 actions → 一个分支可以触发多个（Agent 判定几个就是几个）===")
S1B = strat({
    "cid": "c1b",
    "branches": [{"id": "clicked",
                  "condition": {"signal": "email.click", "op": ">=", "value": 1},
                  "endpoint": {"tags": ["clicked"], "stage": "engaged",
                               "landing_page": "LP_B", "terminal": True},
                  "actions": ["tags", "stage"]}],
})
p1b = compile(GOAL, S1B)
g1b = by_id(p1b["graph"])
b_ep = [n["id"] for n in p1b["graph"] if n["id"].startswith("n_fork_clicked_")]
check(b_ep == ["n_fork_clicked_tag", "n_fork_clicked_stage"],
      f"显式 actions=['tags','stage'] → 两个节点都出，落地页不触发（{b_ep}）")
check([g1b[i]["type"] for i in b_ep] == ["tag.write", "stage.change"], "类型正确")
check(g1b["n_fork_clicked_tag"]["next"] == "n_fork_clicked_stage",
      "多动作按 tags→stage→segment→email→lp→form 顺序串联")
check("next" not in g1b["n_fork_clicked_stage"], "terminal=True → 分支在此收口")
check("n_fork_clicked_lp" not in g1b, "actions 没列 landing_page → 不触发")
check(not [w for w in p1b.get("compile_warnings", []) if "只触发" in w],
      "显式声明 actions → 不再产生「只触发一个」的推断 warning")

print("\n=== b. 3 个分叉 → 3 个决策节点，顺序/id 与声明一致 ===")
S3 = strat({
    "cid": "c3", "name": "三分支",
    "branches": [
        {"id": "clicked", "when": {"signal": "email.click", "op": ">=", "value": 1},
         "endpoint": {"tags": ["hot"]}},
        {"id": "opened", "when": {"signal": "email.open", "op": ">=", "value": 2},
         "endpoint": {"tags": ["warm"]}},
        {"id": "no_open", "when": {"signal": "page.hit"},
         "endpoint": {"segment": "SEG_COLD"}},
    ],
})
p3 = compile(GOAL, S3)
g3 = by_id(p3["graph"])
forks = [n for n in p3["graph"] if n["id"].startswith("n_fork_") and "_tag" not in n["id"]
         and "_seg" not in n["id"]]
check(len([b for b in S3["branches"]]) == 3, "spec 声明 3 个分叉")
check(len(forks) == 3, f"事件图恰好 3 个分叉决策节点（{len(forks)}）")
check([f["id"] for f in forks] == ["n_fork_clicked", "n_fork_opened", "n_fork_no_open"],
      "分叉节点顺序与 id 与声明一致")
check([f["type"] for f in forks] ==
      ["decision.clicked", "decision.opened", "decision.page_hit"],
      f"信号 → 决策类型：click/open/page.hit（{[f['type'] for f in forks]}）")
check(g3["n_fork_clicked"]["params"]["if_false"] == "n_fork_opened"
      and g3["n_fork_opened"]["params"]["if_false"] == "n_fork_no_open"
      and g3["n_fork_no_open"]["params"]["if_false"] == "n_tag",
      "分叉串成 if/elif 阶梯（未命中 → 下一个分叉 → 主流程）")
check(g3["n_fork_opened"]["params"]["op"] == ">=" and g3["n_fork_opened"]["params"]["value"] == 2,
      "每个分叉各自的条件（open >= 2）")
check(g3["n_fork_no_open"]["params"]["op"] == "exists",
      "只有 signal 的条件 → op=exists")

print("\n=== c. 终点 tags + stage + landing_page：推断只触发打标（观测型排最后）===")
S4 = strat({
    "cid": "c4",
    "branches": [{"id": "b1", "condition": {"signal": "email.click"},
                  "endpoint": {"tags": ["clicked"], "stage": "engaged",
                               "landing_page": "LP_B", "terminal": True}}],
})
p4 = compile(GOAL, S4)
g4 = by_id(p4["graph"])
b1 = [n["id"] for n in p4["graph"] if n["id"].startswith("n_fork_b1_")]
check(b1 == ["n_fork_b1_tag"], f"email.click → 只触发打标（{b1}）")
check([g4[i]["type"] for i in b1] == ["tag.write"], "tags → tag.write（Mautic 真能执行）")
check(g4["n_fork_b1_tag"]["params"]["tags"] == ["clicked"], "打标内容来自 spec")
check("next" not in g4["n_fork_b1_tag"], "terminal=True → 该分支到此为止（无 next）")
check(any("忽略「阶段、落地页」" in w for w in p4.get("compile_warnings", [])),
      f"warning 列明被忽略的两类（{p4.get('compile_warnings')}）")

print("\n=== c1b. 只声明观测型落地页（没有可动作类型）→ 仍出落地页节点 ===")
S4D = strat({
    "cid": "c4d",
    "branches": [{"id": "b4", "condition": {"signal": "email.click"},
                  "endpoint": {"landing_page": "LP_ONLY"}}],
})
p4d = compile(GOAL, S4D)
b4 = [n["id"] for n in p4d["graph"] if n["id"].startswith("n_fork_b4_")]
check(b4 == ["n_fork_b4_lp"], f"只有落地页可声明 → 就出落地页（{b4}）")
check(by_id(p4d["graph"])["n_fork_b4_lp"]["params"]["landing_page_ref"] == "LP_ONLY",
      "落地页 ref 来自 spec")

print("\n=== c2. 文案线索优先：分支描述写「打标并升阶段」→ 触发阶段 ===")
S4B = strat({
    "cid": "c4b",
    "branches": [{"id": "b2", "note": "点击后升级到 engaged 阶段",
                  "condition": {"signal": "email.click"},
                  "endpoint": {"tags": ["clicked"], "stage": "engaged"}}],
})
p4b = compile(GOAL, S4B)
b2 = [n["id"] for n in p4b["graph"] if n["id"].startswith("n_fork_b2_")]
check(b2 == ["n_fork_b2_stage"], f"note 里的「阶段」线索命中 → 只触发阶段（{b2}）")

print("\n=== c3. actions 里写了没声明内容的类型 → 跳过并记 warning ===")
S4C = strat({
    "cid": "c4c",
    "branches": [{"id": "b3", "condition": {"signal": "email.click"},
                  "endpoint": {"tags": ["clicked"], "actions": ["tags", "email"]}}],
})
p4c = compile(GOAL, S4C)
b3 = [n["id"] for n in p4c["graph"] if n["id"].startswith("n_fork_b3_")]
check(b3 == ["n_fork_b3_tag"], f"actions 要 email 但终点没声明 email → 只打标（{b3}）")
check(any("email" in w and "没声明" in w for w in p4c.get("compile_warnings", [])),
      f"记 warning 说明跳过了什么（{p4c.get('compile_warnings')}）")

print("\n=== d. stage_rules：升级 / 降级 ===")
S5 = strat({
    "cid": "c5",
    "stage_rules": [
        {"from": "lead", "to": "mql",
         "when": {"signal": "form.submit", "op": ">=", "value": 1}},
        {"from": "mql", "to": "lead", "when": "email.unsub", "direction": "down"},
    ],
})
p5 = compile(GOAL, S5)
g5 = by_id(p5["graph"])
check("n_stage_rule_1" in g5 and "n_stage_rule_2" in g5, "2 条阶段规则 → 2 个阶段节点")
r1, r2 = g5["n_stage_rule_1"], g5["n_stage_rule_2"]
check(r1["type"] == "stage.change" and r2["type"] == "stage.change", "阶段节点类型 stage.change")
check(r1["params"]["direction"] == "up", "未写 direction → up（升级，审计可见）")
check(r2["params"]["direction"] == "down", "显式 direction=down（降级，审计可见）")
check(r1["params"]["from"] == "lead" and r1["params"]["to"] == "mql", "from/to 来自 spec")
check(r1["params"]["when"] == {"signal": "form.submit", "op": ">=", "value": 1},
      "阶段规则携带 when 条件")
check(g5["n_tag"]["next"] == "n_stage_rule_1", "主流程：落库 tag → 阶段规则 → …")
check(r1["next"] == "n_stage_rule_2" and r2["next"] == "n_log", "阶段规则顺序串联后接记账")

print("\n=== e. main_endpoint：主流程终点 + 终点判断 ===")
S6 = strat({
    "cid": "c6",
    "main_endpoint": {"tags": ["converted"], "stage": "customer", "terminal": True,
                      "judgment": {"signal": "page.hit", "op": ">=", "value": 2}},
})
p6 = compile(GOAL, S6)
g6 = by_id(p6["graph"])
check("n_main_judge" in g6, "终点判断 → n_main_judge 节点")
check(g6["n_main_judge"]["type"] == "decision.page_hit", "judgment 信号 page.hit → 页面决策")
jp = g6["n_main_judge"]["params"]
check(jp["op"] == ">=" and jp["value"] == 2, "终点判断的 op/value 来自 spec")
check(jp["if_true"] == "n_main_ep_tag" and jp["if_false"] == "n_log",
      "命中 → 主流程终点；未命中 → 记账结束")
# 主流程终点也走同一套判定：page.hit 语义优先级是「表单 → 打标 → 分组 → …」，
# 没声明表单 → 判定只打标（不再 tags+stage 一起触发）
check([n["type"] for n in p6["graph"] if n["id"].startswith("n_main_ep_")] ==
      ["tag.write"], "主流程终点只触发判定出来的那一个动作（打标）")
check("next" not in g6["n_main_ep_tag"], "terminal=True → 主流程在此收口（无 next）")
check(g6["n_tag"]["next"] == "n_main_judge", "落库 tag 后进入主流程终点判断")

print("\n=== f. 老 spec（无 branches）→ 输出与改动前一致 ===")
S_OLD = strat({"cid": "c_old", "name": "老规格首波",
               "segment": {"mode": "reuse", "ref": "SEG_OLD"},
               "email": {"mode": "reuse", "ref": "EM_OLD", "brief": {"subject": "老主题"}},
               "send_conditions": {"delay_hours": 48, "max_per_24h": 2, "max_per_7d": 5},
               "tags_to_write": ["wave_old"]})
p_old = compile(GOAL, S_OLD)
OLD_TYPE_SEQ = [
    "decision.segment", "guardrail", "sourcemarketing.frequency_gate",
    "anchor_arbitration", "email.send", "wait", "observer.click",
    "decision.clicked", "page.hit", "email.send", "tag.write",
    "log_channel_send", "sms.send.reserved",
]
check(types_of(p_old["graph"]) == OLD_TYPE_SEQ,
      f"节点类型序列与改动前一致（{types_of(p_old['graph'])}）")
check([n["id"] for n in p_old["graph"]][:3] == ["n_decision", "n_guardrail", "n_freq_gate"],
      "治理节点 id/位置不变")
check(p_old["graph"][-3]["next"] == "n_log" and p_old["graph"][-2]["id"] == "n_log",
      "无阶段规则/主终点时 n_tag → n_log（原有收口不变）")
check("compile_warnings" not in p_old, "无降级 → 不产生 compile_warnings 键")
check("window" not in p_old["campaign"], "无 window → 不产生 campaign.window 键")
check(p_old["campaign"]["start_date"] == GOAL.start_date
      and p_old["campaign"]["end_date"] == GOAL.end_date, "无 window → 起止日沿用 GoalSpec")

print("\n=== g. window：活动周期约束 ===")
S7 = strat({"cid": "c7", "window": {"start": "2028-05-01", "end": "2028-07-09"}})
p7 = compile(GOAL, S7)
check(p7["campaign"]["window"] == {"start": "2028-05-01", "end": "2028-07-09"},
      "window 标注到 proposal.campaign")
check(p7["campaign"]["start_date"] == "2028-05-01" and p7["campaign"]["end_date"] == "2028-07-09",
      "window 约束 campaign 起止日")

print("\n=== h. 未知信号 → 回落通用决策 + 记 warning ===")
S8 = strat({"cid": "c8", "branches": [{"id": "weird", "condition": {"signal": "sms.reply"}}]})
p8 = compile(GOAL, S8)
g8 = by_id(p8["graph"])
check(g8["n_fork_weird"]["type"] == GENERIC_DECISION_TYPE, "未知信号 → 通用决策节点")
check(g8["n_fork_weird"]["params"].get("fallback") is True, "节点上标记 fallback（可审计）")
check(any("sms.reply" in w for w in p8.get("compile_warnings", [])),
      f"proposal 记录 warning（{p8.get('compile_warnings')}）")

print("\n=== i. 分叉图 → Mautic events + canvasSettings 合法 ===")
for label, p in (("3 分叉", p3), ("终点齐全", p4), ("阶段规则", p5), ("主终点判断", p6)):
    events, canvas = check_invariants(p, label)
    check(len(events) > 0 and len(canvas["connections"]) > 0, f"{label}：事件与连线都非空")
    types = sorted({e["type"] for e in events})
    check(all(t for t in types), f"{label}：事件类型均非空（{types}）")
# 分叉真的落成了 Mautic decision 事件（不是被透传丢弃）
ev3 = p3["mautic_events"]
mtypes = [e["type"] for e in ev3]
check("email.click" in mtypes and "email.open" in mtypes and "page.pagehit" in mtypes,
      f"3 个分叉落成 Mautic 原生 decision（{mtypes}）")
dec_events = [e for e in ev3 if e["eventType"] == "decision"]
check(all(e["children"] for e in dec_events), "每个决策事件都有子事件（分支不是死路）")
yes_no = sorted({c["anchors"]["source"] for c in p3["mautic_canvas"]["connections"]
                if c["anchors"]["source"] in ("yes", "no")})
check(set(yes_no) == {"yes", "no"} or yes_no, f"决策分支使用 yes/no 锚点（{yes_no}）")
# 顺序连线用 bottom，lead source 用 leadsource
seq = [c for c in p3["mautic_canvas"]["connections"]
       if c["anchors"]["source"] == "bottom"]
check(len(seq) > 0, "顺序连线使用 bottom 锚点")

print("\n=== j. plan_hash 与事件图一致（确定性）===")
import copy  # noqa: E402
import hashlib  # noqa: E402
canon = json.dumps(p3["graph"], ensure_ascii=False, sort_keys=True)
check(p3["plan_hash"] == hashlib.sha256(canon.encode("utf-8")).hexdigest(),
      "plan_hash = 事件图规范 JSON 的 sha256")
p3b = compile(GOAL, copy.deepcopy(S3))
check(p3b["plan_hash"] == p3["plan_hash"], "同一策略两次编译 plan_hash 稳定")
S3_mod = copy.deepcopy(S3)
S3_mod["branches"][0]["endpoint"]["tags"] = ["hot_v2"]
check(compile(GOAL, S3_mod)["plan_hash"] != p3["plan_hash"],
      "改一个终点 tag → plan_hash 变化（审批与执行绑定）")

print("\n=== k. 所有新节点类型都有 Mautic 映射（不会漏成未知 type）===")
for t in ("decision.opened", "decision.page_hit", "decision.form_submit", "decision.generic",
          "stage.change", "segment.change", "form.submit"):
    check(t in _MAUTIC_TYPE, f"{t} 已在 _MAUTIC_TYPE 中登记（{_MAUTIC_TYPE.get(t)}）")

print("\n=== 汇总 ===")
if fails:
    print(f"\n❌ {len(fails)} 项失败：")
    for f in fails:
        print("  - " + f)
    raise SystemExit(1)
print("\n✅ 全部通过（分叉数/条件/终点/阶段规则/主流程终点/window 均由 StrategySpec 驱动，"
      "老 spec 输出不变，Mautic 事件图不变量成立）")
