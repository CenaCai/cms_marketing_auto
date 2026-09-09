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


def topology_default_strategy(goal) -> dict:
    """
    未提交 StrategySpec 时的「基础路径拓扑缺省」：只产出拓扑核心路径的**最小实例**——
    单 campaign，所有内容取自 GoalSpec（分群 / 落地页 / 目标），**不发明**波次、
    延迟、变体、标签。真正的多 campaign 组合与全部内容由 Agent 的 StrategySpec 决定
    （频次 / 折扣 / 内容重点 / #campaigns 都是策略本体，不是这里硬编码的叠加层）。
    """
    seg = getattr(goal, "audience_segment", "") or ""
    cap = getattr(goal, "frequency_cap", None) or {}
    return {
        "cid": f"{goal.goal_id}_c1",
        "wave_id": "wave_1",
        "variant_id": "v1",
        "content_variant": 1,
        "content_variant_spec": {"id": "v1", "angle": "", "headline": goal.objective, "summary": ""},
        "segment": seg,
        "segment_mode": "reuse",
        "email_ref": f"EM_{goal.goal_id}_PLACEHOLDER",
        "email_mode": "reuse",
        "email_pending": False,
        "email_followup_ref": f"EM_{goal.goal_id}_FOLLOWUP_PLACEHOLDER",
        "campaign_name": f"[拓扑缺省] {goal.objective}",
        "send_conditions": {
            "delay_hours": 24,
            "max_per_24h": cap.get("max_per_24h", 1) if isinstance(cap, dict) else 1,
            "max_per_7d": cap.get("max_per_7d", 3) if isinstance(cap, dict) else 3,
        },
        "tags_to_write": ["wave_1"],
        "rationale": "未提交 StrategySpec：仅以基础路径拓扑 + GoalSpec 派生单 campaign（无多波递进）",
        "evidence": "",
        "strategy_source": "topology_default",
        "intent": "promo",
        "journey": "promo",
        "discount": None,
    }


# =====================================================================
# 落地页 / 表单意图识别（objective 关键词自动识别）
# ---------------------------------------------------------------------
# 用户常把「要落地页 + 表单、提交表单作为流程终点」写在 objective 自由文本里，
# 但历史上这条意图从未被结构化（strategy 只填 email、landing_page_ref 恒空），
# 导致编译层与 push 层即便具备能力也不会生成落地页/表单。这里把意图提取出来，
# 注入 strategy 的 landing_page_ref / form_ref / main_endpoint，让 plan_compiler
# 吐出 page.hit / form.submit 节点、push 真实建 Mautic 落地页+表单资产。
# =====================================================================
_LP_KEYWORDS = ("落地页", "着陆页", "landing page", "landing_page", "lp",
                "报名页", "留资页", "表单页")
_FORM_KEYWORDS = ("表单", "form", "报名", "提交表单", "填写个人信息",
                  "留资", "收集信息", "个人信息", "收集")


def _goal_requests_lp_form(goal) -> tuple:
    """扫描 objective + constraints 自由文本，返回 (needs_lp, needs_form)。

    needs_form 为真时一并要求落地页（表单需有承载页；用户多要求「落地页中有表单」）。
    """
    text = " ".join(str(x or "") for x in (
        getattr(goal, "objective", ""),
        getattr(goal, "constraints", ""),
    )).lower()
    needs_form = any(k in text for k in _FORM_KEYWORDS)
    needs_lp = any(k in text for k in _LP_KEYWORDS) or needs_form
    return needs_lp, needs_form


def _enrich_lp_form(strategy: dict, goal, needs_lp: bool, needs_form: bool) -> dict:
    """策略未显式声明落地页/表单时，按 objective 意图注入 landing_page + form 终点。

    尊重显式意图：strategy 已带 landing_page_ref / form_ref 时不覆盖（Agent/规格优先）。
    注入后 plan_compiler 会从 main_endpoint 吐出 page.hit / form.submit 节点，
    push 再据此真实建 Mautic 落地页（内嵌表单）+ 表单资产。
    """
    if not (needs_lp or needs_form):
        return strategy
    s = strategy if isinstance(strategy, dict) else {}
    cname = (s.get("campaign_name")
             or getattr(goal, "goal_id", "campaign") or "campaign")

    # 落地页
    if needs_lp and not s.get("landing_page_ref"):
        s["landing_page_mode"] = "generate"
        s["landing_page_ref"] = f"LP_{cname}"
        if "landing_page_url" not in s:
            s["landing_page_url"] = ""

    # 表单
    if needs_form and not s.get("form_ref"):
        s["form_ref"] = f"FORM_{cname}"

    # 主流程终点：以「提交表单」收口（落地页承接）
    mep = s.get("main_endpoint")
    if not isinstance(mep, dict):
        mep = {"tags": [], "stage": None, "segment": None, "email": None,
               "landing_page": None, "form": None, "terminal": True,
               "actions": [], "note": "", "action": "add", "judgment": None}
        s["main_endpoint"] = mep
    if needs_lp and not mep.get("landing_page"):
        mep["landing_page"] = s.get("landing_page_ref") or f"LP_{cname}"
    if needs_form and not mep.get("form"):
        mep["form"] = s.get("form_ref") or f"FORM_{cname}"
    mep["terminal"] = True
    # 显式声明终点动作，避免 _infer_endpoint_action 只挑一个（落地页与表单都要触发）
    acts = list(mep.get("actions") or [])
    for k in ("landing_page", "form"):
        if mep.get(k) and k not in acts:
            acts.append(k)
    mep["actions"] = acts
    # 主流程终点判断信号：form.submit 才收口（以提交表单为流程终点）
    if needs_form:
        mep["judgment"] = {
            "signal": "form.submit", "op": "exists", "value": True,
            "ref": mep.get("form"), "note": "以提交表单作为流程终点",
        }
    return s


def default_strategies(goal, n: int = 1) -> list:
    """
    [废弃别名] 原 N 波递进占位已改为「拓扑缺省单 campaign」。保留仅为兼容旧 import。
    真正多 campaign 应由 StrategySpec 决定，勿再调用本函数编造波次。
    """
    s = topology_default_strategy(goal)
    return [s]


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
        # 已提交 StrategySpec：N 由策略数组长度决定（Agent 的策略本体，#campaigns 是策略决策）
        strategies = list(strategy_spec)
        n = len(strategies)
    else:
        # 拓扑缺省：基础路径单 campaign，内容全来自 GoalSpec，不发明波次
        s = topology_default_strategy(goal)
        strategies = [s] if isinstance(s, dict) else list(s)
        n = len(strategies)
    campaigns = []
    _needs_lp, _needs_form = _goal_requests_lp_form(goal)
    for s in strategies:
        # objective 关键词自动识别：要求落地页/表单且策略未显式声明时注入终点
        _enrich_lp_form(s, goal, _needs_lp, _needs_form)
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


def _verdict_for(target, conv: float, unsub: float) -> str:
    """
    由达成率 + 退订率给出修正判定（确定性，可审计）：
      burn  = 退订率 > 0.003（熔断）
      strong= 达成率 >= 100%
      ok    = 50% <= 达成率 < 100%
      weak  = 达成率 < 50%
      baseline = 无目标（不触发改写）
    """
    if unsub and unsub > 0.003:
        return "burn"
    if target is None or target <= 0:
        return "baseline"
    ratio = conv / float(target)
    if ratio >= 1.0:
        return "strong"
    if ratio >= 0.5:
        return "ok"
    return "weak"


def _reengage_branch_strategy(goal, done_c: dict, discount_pct: int = 10) -> dict:
    """
    修正循环：为「转化乏力」的源 campaign 新增一条折扣挽回分支（branch 维度）。
    覆盖未转化联系人（建议真实落地时为源 segment + not_converted 过滤；
    PoC 记 segment_ref + segment_note 供 Agent 补建 SEG_<goal>_UNENGAGED）。
    """
    src = done_c.get("strategy", {})
    seg = src.get("segment") or getattr(goal, "audience_segment", "") or ""
    cid = f"{goal.goal_id}_reengage_{done_c['cid']}"
    return {
        "cid": cid,
        "wave_id": "wave_reengage",
        "variant_id": "v_reengage",
        "campaign_name": f"[修正分支] 折扣挽回 · 来自 {done_c['cid']}",
        "strategy_source": "replan_branch",
        "intent": "promo",
        "journey": "promo",
        "segment": seg,
        "segment_mode": "reuse",
        "segment_note": f"源 campaign {done_c['cid']} 未转化联系人（建议 SEG_{goal.goal_id}_UNENGAGED）",
        "segment_broaden": False,
        "email_ref": f"EM_{cid}_PLACEHOLDER",
        "email_mode": "generate",
        "email_pending": True,
        "email_followup_ref": f"EM_{cid}_FOLLOWUP_PLACEHOLDER",
        "email_brief": {"subject": f"专属 {int(discount_pct)}% 折扣，最后机会",
                        "angle": "折扣挽回", "cta": "立即使用", "locale": []},
        "subject": f"专属 {int(discount_pct)}% 折扣，最后机会",
        "followup_subject": "提醒：您的专属折扣即将失效",
        "content_variant": 1,
        "content_variant_spec": {"id": "v_reengage", "angle": "折扣挽回", "headline": "", "summary": ""},
        "landing_page_ref": src.get("landing_page_ref", ""),
        "landing_page_url": src.get("landing_page_url", ""),
        "send_conditions": {"delay_hours": 24, "max_per_24h": 1, "max_per_7d": 2},
        "tags_to_write": ["reengage", f"branch_of_{done_c['cid']}"],
        "discount": {"enabled": True, "pct": int(discount_pct),
                     "note": "修正循环：源 campaign 转化乏力，开启挽回折扣分支"},
        "rationale": f"evaluate_and_replan 修正：源 campaign {done_c['cid']} 转化<50% 目标，"
                     f"新增折扣挽回分支覆盖未转化联系人",
        "evidence": "",
        "success_criteria": None,
        "deferred": False,
        "deferred_reason": "",
        "trigger": None,
    }


def _soften_angle(s: dict) -> None:
    """退订熔断：把邮件角度软化为价值导向（非促销），不改动策略其它字段。"""
    brief = s.get("email_brief")
    if not isinstance(brief, dict):
        brief = {}
    brief = dict(brief)
    brief["angle"] = "价值导向（非促销）"
    s["email_brief"] = brief


def _steer_angle_discount(s: dict) -> None:
    """转化乏力：把邮件角度转向折扣挽回，与开启的折扣策略一致。"""
    brief = s.get("email_brief")
    if not isinstance(brief, dict):
        brief = {}
    brief = dict(brief)
    brief["angle"] = "折扣挽回"
    s["email_brief"] = brief


def evaluate_and_replan(program: dict, completed_cid: str, result: dict) -> dict:
    """
    标记 completed_cid 完成，并**修订完整策略**（确定性、可审计）：
      1) 频次（send_conditions.max_per_24h）
      2) 内容（content_variant 换变体 + email 角度）
      3) 折扣（discount 开启 / 加码 / 退守）——策略本体，来自意图识别
      4) 受众（segment_broaden / segment_narrow 标记，供 Agent 补建分群资产）
      5) 分支（branch 维度）：转化乏力→新增折扣挽回分支 campaign；达标→剪掉挂起的兜底/挽回分支

    返回 { ratio, verdict, changes(下游 knob 改写), new_campaigns(新增分支),
           pruned_campaigns(剪掉分支), target_unset }。
    result: {"conversion": float(0~1), "unsub": float(0~1)}（可含 feedback_auto 明细）
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
    verdict = "baseline" if target_unset else _verdict_for(target, conv, unsub)

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
        disc = s.get("discount") if isinstance(s.get("discount"), dict) else {}
        notes = []

        if verdict == "baseline":
            notes.append("KPI 目标未设置（R 未给）：不做达成率改写，仅记录基线")
        elif verdict == "burn":
            # 退订熔断：降频 + 收窄 + 软化内容 + 折扣退守
            sc["max_per_24h"] = max(1, m24 - 1)
            tags.append("suppressed")
            s["segment_narrow"] = True
            if disc.get("enabled"):
                new_pct = max(0, int(disc.get("pct", 0)) // 2)
                if new_pct <= 0:
                    disc["enabled"] = False
                    notes.append("退订熔断：折扣退守至关闭")
                else:
                    disc["pct"] = new_pct
                    notes.append(f"退订熔断：折扣退守至 {new_pct}%")
            else:
                notes.append("退订熔断：折扣本就未启用，保持不变")
            _soften_angle(s)
            notes.append("退订率超阈：降频 + 收窄 + 软化内容角度")
        elif verdict == "strong":
            # 达标：保持，略降本（降频）
            sc["max_per_24h"] = max(1, m24 - 1)
            notes.append("达标：保持策略，略降本（降频）")
        elif verdict == "ok":
            # 未达标(50%~100%)：提频 + 换内容变体 + urgency tag
            sc["max_per_24h"] = m24 + 1
            s = _bump_variant(s)
            tags.append("urgency")
            notes.append("未达标(50%~100%)：提频 + 换内容变体 + urgency tag")
        else:  # weak
            # 乏力：大幅提频 + 扩分组 + 换内容 + 折扣挽回
            sc["max_per_24h"] = m24 + 2
            tags.append("broaden")
            tags.append("reengage")
            s = _bump_variant(s)
            s["segment_broaden"] = True
            if not disc.get("enabled"):
                disc = {"enabled": True, "pct": 10, "note": "修正：转化乏力，开启挽回折扣"}
                notes.append("转化乏力：开启 10% 挽回折扣")
            else:
                disc["pct"] = int(disc.get("pct", 0)) + 5
                notes.append(f"转化乏力：折扣加码至 {disc['pct']}%")
            _steer_angle_discount(s)
            notes.append("乏力：大幅提频 + 扩分组 + 换内容 + 折扣挽回分支")

        if disc:
            s["discount"] = disc
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

    # ---- 分支维度（第 3 轴）：依赖 completed 的 verdict，独立于逐 campaign knob 改写 ----
    new_campaigns = []
    pruned_campaigns = []
    if verdict == "weak":
        branch_cid = f"{goal.goal_id}_reengage_{completed_cid}"
        if not any(c["cid"] == branch_cid for c in campaigns):
            nb = _reengage_branch_strategy(goal, done)
            nb_prop = compile(goal, nb)
            new_campaigns.append({
                "cid": nb["cid"], "wave_id": nb["wave_id"], "strategy": nb,
                "plan_hash": nb_prop["plan_hash"],
                "notes": ["修正循环：新增折扣挽回分支（覆盖未转化联系人）"],
            })
            campaigns.append({
                "cid": nb["cid"], "wave_id": nb["wave_id"], "strategy": nb,
                "proposal": nb_prop, "status": "unreviewed", "result": None,
            })
    elif verdict == "strong":
        # 达标：剪掉仍挂起的兜底/挽回分支（不再需要）
        for c in campaigns:
            strat = c.get("strategy") or {}
            # tag 可能在 campaign 级或 strategy 级，二者都查（人类建的兜底分支常只在 strategy 级）
            tags_c = c.get("tags_to_write") or strat.get("tags_to_write") or []
            is_branch = (f"branch_of_{completed_cid}" in tags_c
                         or c["cid"].endswith(f"_reengage_{completed_cid}")
                         or c["cid"].endswith(f"_fallback_{completed_cid}"))
            if c["status"] in ("deferred", "pending", "unreviewed") and is_branch:
                c["status"] = "done_met"
                pruned_campaigns.append({
                    "cid": c["cid"],
                    "notes": ["达标：剪掉兜底/挽回分支（不再需要）"],
                })

    program["n_campaigns"] = len(campaigns)
    program["changelog"].append({
        "completed_cid": completed_cid,
        "result": result,
        "ratio": ratio,
        "verdict": verdict,
        "target_unset": bool(target_unset),
        "changes": changes,
        "new_campaigns": new_campaigns,
        "pruned_campaigns": pruned_campaigns,
        "at": time.time(),
    })
    return {
        "ratio": ratio,
        "verdict": verdict,
        "target_unset": bool(target_unset),
        "changes": changes,
        "new_campaigns": new_campaigns,
        "pruned_campaigns": pruned_campaigns,
    }
