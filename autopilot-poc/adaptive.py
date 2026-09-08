"""
adaptive.py — 多 campaign 自适应编排（L1/L2/L6 切片）
=====================================================================
一个 Goal → 一个 Program（N 个 campaign，各带不同策略：邮件变体 / 分组 / 发送条件 / 落库 tag）。
上游 campaign 完成后，按「达成率 + 退订率」确定性改写下游 campaign 的：
  频次（send_conditions.max_per_24h）
  内容（content_variant 换变体）
  发送条件（delay_hours）
  落库 tag / 分组（tags_to_write）
并重算 plan_hash（审批内容随之更新）。

PoC 阶段「达成情况」由运营在驾驶舱模拟回填（真实系统由 Mautic Observer/L5 回写）。
规则确定性、可审计（写入 program.changelog），不靠 LLM 临场发挥。
"""
from __future__ import annotations

import math
import time
from datetime import date, timedelta
from typing import Optional

# 未提交 StrategySpec 时的默认 campaign 数（fallback，非策略决策）
DEFAULT_N_CAMPAIGNS = 3

# 假设落地页承接转化率（单波点击后真正转化的比例），可调
ASSUMED_LP_CONV = 0.10


def _split_windows(start_date: str, end_date: str, n: int) -> list:
    """
    把 [start_date, end_date] 均分成 n 段连续执行窗口。
    日期解析失败则退化为整段（每段都填原 start/end）。
    """
    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
        span = (e - s).days
    except Exception:  # noqa: BLE001
        return [{"start": start_date, "end": end_date} for _ in range(n)]
    if span <= 0 or n <= 0:
        return [{"start": start_date, "end": end_date} for _ in range(n)]
    step = span / n
    out = []
    for i in range(n):
        ws = s + timedelta(days=int(step * i))
        we = (s + timedelta(days=int(step * (i + 1)))) if i < n - 1 else e
        out.append({"start": ws.isoformat(), "end": we.isoformat()})
    return out


def derive_plan(overall_conv, start_date, end_date, strategy=None) -> dict:
    """
    由「总体目标转化率 + 起止日期」派生 program 计划（确定性启发式；单 campaign 点击率不再手填，改由系统推算）：

      ASSUMED_LP_CONV = 0.10  （假设落地页承接转化率，可调）
      单 campaign 打开/点击率（click_rate）由总体目标转化率反推：
          pc        = 1 - (1-overall_conv)^(1/n)      （每 campaign 需贡献的转化）
          click_rate = pc / ASSUMED_LP_CONV            （= 打开/点击率，系统推算，非运营手填）
      n（campaign 数）= 策略依据「日期跨度(最小节奏 MIN_CADENCE_DAYS) + 总体目标」选出：
          max_by_span = clamp(span_days // MIN_CADENCE_DAYS, 1, 8)   （跨度决定上限）
          取使 click_rate <= RC_MAX 的最小 n；若跨度内无法满足则取 max_by_span 并标记需优化
      windows = [start,end] 均分成 n 段连续执行窗口
      per_campaign_target = round(overall_conv / n, 4)  （线性归因，可编辑）

    返回 {"n_campaigns","windows","per_campaign_target","click_rate","reasonable","optimization_note"}。

    strategy: 可选 dict，可覆盖 MIN_CADENCE_DAYS / max_campaigns / rc_max（Agent 调参入口）。
    """
    try:
        oc = float(overall_conv)
    except (TypeError, ValueError):
        oc = 0.0
    if oc < 0:
        oc = 0.0
    if oc >= 1:
        oc = 0.99  # 转化率上限保护，避免 (1-oc) 非正导致幂运算异常

    # 策略参数（Agent 可按 StrategySpec 调参）
    MIN_CADENCE_DAYS = 7
    MAX_CAMPAIGNS = 8
    RC_MAX = 0.50
    if isinstance(strategy, dict):
        MIN_CADENCE_DAYS = int(strategy.get("min_cadence_days", MIN_CADENCE_DAYS))
        MAX_CAMPAIGNS = int(strategy.get("max_campaigns", MAX_CAMPAIGNS))
        RC_MAX = float(strategy.get("rc_max", RC_MAX))

    # 日期跨度
    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
        span = (e - s).days
    except Exception:  # noqa: BLE001
        span = 0
    if span < 0:
        span = 0
    max_by_span = (max(1, min(MAX_CAMPAIGNS, span // MIN_CADENCE_DAYS))
                   if span > 0 else MAX_CAMPAIGNS)

    if oc <= 0:
        n = max_by_span if span > 0 else DEFAULT_N_CAMPAIGNS
        per_campaign_target = 0.0
        click_rate = 0.0
        reasonable = True
        opt_note = "未配置总体目标转化率：跳过可达性校验，n 按日期跨度默认派生"
    else:
        # 选使 click_rate <= RC_MAX 的最小 n（在跨度上限内）
        n = None
        for k in range(1, max_by_span + 1):
            pc = 1 - (1 - oc) ** (1.0 / k)
            cr = pc / ASSUMED_LP_CONV if ASSUMED_LP_CONV > 0 else 0.0
            if cr <= RC_MAX:
                n = k
                break
        if n is None:
            n = max_by_span
        pc = 1 - (1 - oc) ** (1.0 / n)
        click_rate = round(pc / ASSUMED_LP_CONV, 4) if ASSUMED_LP_CONV > 0 else 0.0
        per_campaign_target = round(oc / n, 4)
        reasonable = (click_rate <= RC_MAX) and (n <= MAX_CAMPAIGNS)
        if not reasonable:
            opt_note = ("单 campaign 点击率超阈值：Agent 将按策略压缩节奏 / 提升单波内容转化以满足总体目标")
        else:
            opt_note = "默认递进策略派生；Agent 可按 StrategySpec 进一步优化频次 / 内容 / 受众"

    windows = _split_windows(start_date, end_date, n)
    return {
        "n_campaigns": n,
        "windows": windows,
        "per_campaign_target": per_campaign_target,
        "click_rate": click_rate,
        "reasonable": reasonable,
        "optimization_note": opt_note,
    }

# L1 策略规格加载：Agent 产出 → PoC 消费（re-export，方便调用方一处 import）
from strategy_spec import (  # noqa: F401  (re-export)
    load_strategy_spec, parse_strategy_spec, strategies_from_spec,
    service_sequences_from_spec, spec_goal_defaults, email_display,
    normalize_campaign, normalize_service_sequence,
)


def default_strategies(goal, n: int) -> list:
    """
    为 N 个 campaign 生成差异化默认策略（逐波递进：延迟递增、变体递增）。
    ⚠️ 这是 fallback：真实策略应由 Agent（人+LLM）产出 StrategySpec，
       经 build_program(strategy_spec=...) 注入。保留它是为了 CLI / 未提交策略时不破。
    """
    base_seg = goal.audience_segment
    out = []
    for i in range(n):
        out.append({
            "cid": f"{goal.goal_id}_c{i+1}",
            "wave_id": f"wave_{i+1}",
            "variant_id": f"v{i+1}",
            "content_variant": i,
            "content_variant_spec": {"id": f"v{i+1}", "angle": "", "headline": "", "summary": ""},
            "segment": base_seg,
            "segment_mode": "reuse",
            "email_ref": f"EM_WAVE{i+1}_PLACEHOLDER",
            "email_mode": "reuse",
            "email_pending": False,
            "email_followup_ref": f"EM_WAVE{i+1}_FOLLOWUP_PLACEHOLDER",
            "campaign_name": f"[PoC] {goal.objective} · 波次{i+1}",
            "send_conditions": {"delay_hours": 24 * (i + 1), "max_per_24h": 1, "max_per_7d": 3},
            "tags_to_write": [f"wave_{i+1}"],
            "rationale": "",
            "evidence": "",
            "strategy_source": "default",
        })
    return out


def build_program(goal, n: int = DEFAULT_N_CAMPAIGNS, compile_fn=None,
                  strategy_spec: Optional[list] = None,
                  service_sequences: Optional[list] = None) -> dict:
    """
    编译出含 N 个 campaign 的 Program（每个 campaign 一份事件图提案）。

    strategy_spec: Agent 产出的 promo 策略列表（见 strategy_spec.load_strategy_spec）；
                   传入时 N 由策略数组长度决定（忽略 n 参数）。
                   未传入时回落 default_strategies(goal, n)。
    service_sequences: 与 campaigns 平级的 service/transactional 序列，
                   单独挂在 program["service_sequences"]，不混进 promo Program
                   （否则会被 promo 的 suppress_promo 规则吃掉）。
    """
    from plan_compiler import compile
    if strategy_spec:
        strategies = list(strategy_spec)
        n = len(strategies)
    else:
        strategies = default_strategies(goal, n)
    campaigns = []
    for s in strategies:
        prop = compile_fn(goal, s) if compile_fn else compile(goal, s)
        campaigns.append({
            "cid": s["cid"], "wave_id": s["wave_id"],
            "strategy": s, "proposal": prop,
            # deferred：外部事件触发的波次，不得到期自动发送，需运营启用
            "status": "deferred" if s.get("deferred") else "unreviewed",
            "result": None,
        })
    services = []
    for s in (service_sequences or []):
        prop = compile_fn(goal, s) if compile_fn else compile(goal, s)
        services.append({
            "sid": s.get("sid") or s["cid"], "cid": s["cid"], "wave_id": s.get("wave_id", "svc"),
            "strategy": s, "proposal": prop,
            "status": "armed",          # 事件驱动：待触发，不进 promo 排期
            "result": None,
        })
    return {
        "goal_id": goal.goal_id,
        "goal": goal.to_dict(),
        "n_campaigns": n,
        "n_service_sequences": len(services),
        "strategy_source": (strategies[0].get("strategy_source", "default")
                            if strategies else "default"),
        "campaigns": campaigns,
        "service_sequences": services,
        "created_at": time.time(),
        "changelog": [],
    }


def _bump_variant(s: dict) -> dict:
    """换内容变体：int 序号 +1，同步刷新变体实体 id（展示用，不影响阈值规则）。"""
    v = s.get("content_variant", 0) + 1
    s["content_variant"] = v
    spec = s.get("content_variant_spec")
    if isinstance(spec, dict):
        spec = dict(spec)
        spec["id"] = f"v{v}"
        s["content_variant_spec"] = spec
    if s.get("variant_id"):
        s["variant_id"] = f"v{v}"
    return s


def evaluate_and_replan(program: dict, completed_cid: str, result: dict) -> dict:
    """
    标记 completed_cid 完成，并确定性改写其后的 pending campaign。
    result: {"conversion": float(0~1), "unsub": float(0~1)}
    返回 { ratio, changes:[{cid, notes, strategy, plan_hash}] }
    """
    from goal_intake import GoalSpec
    from plan_compiler import compile

    kpi = program["goal"].get("kpi") or {}
    target = kpi.get("target", 0.15)
    # KPI target 未设置（运营还没给 R）时不能算达成率，也不能触发"达标/未达标"改写
    target_unset = target is None or kpi.get("target_unset") or float(target or 0) <= 0
    if target_unset:
        target = None
    campaigns = program["campaigns"]

    done = next((c for c in campaigns if c["cid"] == completed_cid), None)
    if not done:
        return {"error": f"campaign {completed_cid} 不存在"}

    conv = float(result.get("conversion", 0) or 0)
    unsub = float(result.get("unsub", 0) or 0)
    # 达标判定：以本 campaign 的转化目标为准（缺省回落 KPI 目标）
    cmp_target = done.get("conv_target")
    if cmp_target is None:
        cmp_target = target
    met = (conv >= float(cmp_target or 0))
    done["status"] = "done_met" if met else "done_below"
    done["result"] = result

    ratio = (round(conv / target, 3) if target else None)

    goal = GoalSpec(**program["goal"])
    changes = []
    for c in campaigns:
        # 仅改写仍待处理的下游（已完成/执行中/已挂起的不动）
        if c["status"] not in ("unreviewed", "reviewed", "pending"):
            continue
        s = dict(c["strategy"])
        sc = dict(s.get("send_conditions", {}) or {})
        tags = list(s.get("tags_to_write", []))
        m24 = sc.get("max_per_24h", 1)
        notes = []

        if unsub > 0.003:
            # 退订率超熔断阈值：降频 + 收窄 + suppression tag
            sc["max_per_24h"] = max(1, m24 - 1)
            tags.append("suppressed")
            notes.append("退订率超阈：降频 + 加 suppression tag（收窄）")
        elif ratio is None:
            # KPI 目标未设置（R 未给）：不做达成率改写，只记录基线
            notes.append("KPI 目标未设置（R 未给）：不做达成率改写，仅记录基线")
        elif ratio >= 1.0:
            # 达标：保持，略降本（降频）
            sc["max_per_24h"] = max(1, m24 - 1)
            notes.append("达标：保持策略，略降本（降频）")
        elif ratio >= 0.5:
            # 未达标：提频 + 换内容变体 + urgency tag
            sc["max_per_24h"] = m24 + 1
            s = _bump_variant(s)
            tags.append("urgency")
            notes.append("未达标：提频 + 换内容变体 + urgency tag")
        else:
            # 乏力：大幅提频 + 扩分组 + 换内容
            sc["max_per_24h"] = m24 + 2
            tags.append("broaden")
            tags.append("reengage")
            s = _bump_variant(s)
            notes.append("乏力：大幅提频 + 扩分组 tag(broaden/reengage) + 换内容")

        s["send_conditions"] = sc
        s["tags_to_write"] = tags
        c["strategy"] = s
        c["proposal"] = compile(goal, s)   # 重编译 → 新 plan_hash
        changes.append({
            "cid": c["cid"],
            "wave_id": s.get("wave_id"),
            "notes": notes,
            "strategy": s,
            "plan_hash": c["proposal"]["plan_hash"],
        })

    program["changelog"].append({
        "completed_cid": completed_cid,
        "result": result,
        "ratio": ratio,
        "target_unset": bool(target_unset),
        "changes": changes,
        "at": time.time(),
    })
    return {"ratio": ratio, "target_unset": bool(target_unset), "changes": changes}
