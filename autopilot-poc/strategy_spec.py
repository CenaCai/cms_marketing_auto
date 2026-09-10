"""
strategy_spec.py — L1 策略规格（StrategySpec）加载
=====================================================================
设计前提：**L1 策略由 Agent（人 + LLM）产出，PoC 只消费**，不再由代码里的
for 循环硬编码 N 个 campaign（那样只是"手动配置器"）。

本模块负责：
  1. 读取一份 Agent 写的 StrategySpec（文件路径 或 直接贴 JSON 文本）
  2. 归一化成 plan_compiler / adaptive 能直接吃的 strategy dict 列表
     ——每个 campaign 自带：segment / email / content_variant / 发送条件 / 落库 tag
  3. 缺字段一律安全缺省（不会因为 Agent 少写一个字段就崩）

Schema（见 strategies/example_strategy.json）：
{
  "goal_id": "ucl2028",
  "objective": "……",
  "kpi": {"metric": "conversion", "target": 0.15},
  "window": {"start": "2028-05-01", "end": "2028-07-09"},
  "locale": ["zh_CN", "en_US"],
  "budget": 0,
  "campaigns": [
    {
      "cid": "ucl2028_c1",
      "name": "……", "rationale": "……", "evidence": "……",
      "segment": {"mode": "reuse|propose", "ref": "SEG_XXX", "note": "……"},
      "email": {"mode": "reuse|generate", "ref": "EM_XXX 或 null",
                "brief": {"subject": "……", "angle": "……", "cta": "……", "locale": []}},
      "landing_page": {"mode": "reuse|generate", "ref": "LP_XXX", "note": "……"},
      "content_variant": {"id": "v1", "angle": "……", "headline": "……", "summary": "……"},
      "send_conditions": {"delay_hours": 0, "max_per_24h": 1, "max_per_7d": 3,
                          "quiet_hours": "22:00-09:00"},
      "tags_to_write": ["……"],
      "success_criteria": {"metric": "……", "threshold": "……"}
    }
  ]
}

仅使用 Python 标准库。
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

# 发送条件安全缺省（Agent 少写字段时回落，不会崩）
DEFAULT_SEND_CONDITIONS = {"delay_hours": 0, "max_per_24h": 1, "max_per_7d": 3}

HERE = os.path.dirname(os.path.abspath(__file__))


# --------------------------- 读取 ---------------------------
def _is_empty(v) -> bool:
    """空值不覆盖已有非空值（合并规则）。"""
    return v is None or v == "" or v == [] or v == {}


def merge_value(old, new):
    """
    合并两个值：
      - 新值为空 → 保留旧值
      - 旧值为空 → 取新值
      - 都是 dict → 递归合并
      - 都是 list → 并集（保持顺序，去重）
      - 结构 (dict/list) vs 标量 → 保留结构更完整的一方
      - 都是标量 → 后者覆盖前者
    """
    if _is_empty(new):
        return old
    if _is_empty(old):
        return new
    if isinstance(old, dict) and isinstance(new, dict):
        out = dict(old)
        for k, v in new.items():
            out[k] = merge_value(old.get(k), v)
        return out
    if isinstance(old, list) and isinstance(new, list):
        out = list(old)
        for v in new:
            if v not in out:
                out.append(v)
        return out
    if isinstance(old, (dict, list)) and not isinstance(new, (dict, list)):
        return old          # 结构优先：不让标量覆盖结构化字段
    if isinstance(new, (dict, list)) and not isinstance(old, (dict, list)):
        return new
    return new              # 都是标量：后加载的覆盖先加载的


def _merge_by_key(base, extra, key: str):
    """按业务主键（cid / sid）合并数组，保持 base 顺序，extra 独有的追加在后。"""
    base = _as_list(base)
    extra = _as_list(extra)
    if not base:
        return extra
    if not extra:
        return base
    idx = {str(_as_dict(x).get(key)): i for i, x in enumerate(base)}
    out = list(base)
    for x in extra:
        k = str(_as_dict(x).get(key))
        if k in idx:
            out[idx[k]] = merge_value(base[idx[k]], x)
        else:
            out.append(x)
    return out


def merge_spec(base: dict, extra: dict) -> dict:
    """
    合并两份 StrategySpec（如 send_strategy + content_map）：
      - campaigns 按 cid 合并、service_sequences 按 sid 合并
      - 顶层目标字段递归合并（空值不覆盖）
    """
    base, extra = _as_dict(base), _as_dict(extra)
    out = dict(base)
    for k, v in extra.items():
        if k in ("campaigns", "service_sequences"):
            continue
        out[k] = merge_value(base.get(k), v)
    if "campaigns" in base or "campaigns" in extra:
        out["campaigns"] = _merge_by_key(base.get("campaigns"), extra.get("campaigns"), "cid")
    if "service_sequences" in base or "service_sequences" in extra:
        out["service_sequences"] = _merge_by_key(
            base.get("service_sequences"), extra.get("service_sequences"), "sid")
    # 记录来源（供 UI 显示「已合并 N 个策略文件」）
    srcs = list(base.get("_sources") or [])
    for s in (extra.get("_sources") or []):
        if s not in srcs:
            srcs.append(s)
    if srcs:
        out["_sources"] = srcs
    return out


def _split_sources(src) -> list:
    """
    把入参拆成多个 StrategySpec 来源：
      - list/tuple → 逐项递归
      - 单个 JSON 文本（以 { 开头且能解析）→ 整体作为一个来源（不按逗号切）
      - 其余字符串 → 按换行 / 逗号切分
    """
    if src is None:
        return []
    if isinstance(src, (list, tuple)):
        out = []
        for x in src:
            out.extend(_split_sources(x))
        return out
    s = str(src).strip()
    if not s:
        return []
    if s.startswith("{"):
        try:
            json.loads(s)
            return [s]          # 直接贴的 JSON，不切分
        except json.JSONDecodeError:
            pass
    parts = [p.strip() for p in re.split(r"[\n,]+", s) if p.strip()]
    return parts or [s]


def parse_strategy_spec(src) -> dict:
    """
    读入一份或多份 StrategySpec → 合并后的 dict。

    src 可为：
      - str：单个文件路径 / 直接贴的 JSON 文本 / 逗号或换行分隔的多个路径
      - list / tuple of str：多文件（如 [send_strategy.json, content_map.json]）

    合并规则：campaigns 按 cid、service_sequences 按 sid、顶层字段递归合并；
    空值（null/""/[]/{}）不覆盖已有非空值；两边都非空时后加载的覆盖先加载的。
    """
    sources = _split_sources(src)
    if not sources:
        raise ValueError("StrategySpec 为空")
    specs = []
    for s in sources:
        text = s
        if os.path.exists(text) and os.path.isfile(text):
            with open(text, "r", encoding="utf-8") as f:
                text = f.read()
        try:
            d = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"StrategySpec 不是合法 JSON（也不是可读取的文件路径）：{s[:80]} · {e}") from e
        if not isinstance(d, dict):
            raise ValueError(f"StrategySpec 顶层必须是 JSON 对象：{s[:80]}")
        d.setdefault("_sources", [s])
        specs.append(d)
    merged = specs[0]
    for d in specs[1:]:
        merged = merge_spec(merged, d)
    return merged


def spec_goal_defaults(spec: dict) -> dict:
    """
    抽取 StrategySpec 里属于「目标层」的字段，供 L0 Brief 合并
    （目标/窗口/KPI/预算/locale 依然可以来自运营，Agent 只补策略）。
    """
    spec = _as_dict(spec)
    out = {}
    sources = spec.get("_sources")
    if sources:
        out["_sources"] = list(sources)


def _as_dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _as_list(v) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _variant_int(vid: str, fallback: int) -> int:
    """'v2'/'variant-2' → 2；解析不出则回落序号（保持可 +1 的算术语义）。"""
    if isinstance(vid, (int, float)):
        return int(vid)
    m = re.search(r"(\d+)", str(vid or ""))
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return fallback


def _num(v, default):
    if v is None or v == "":
        return default
    if default is None:
        # 无缺省值时按数值推断（int 优先，其次 float）
        try:
            return int(v)
        except (TypeError, ValueError):
            try:
                return float(v)
            except (TypeError, ValueError):
                return default
    try:
        return type(default)(v)
    except (TypeError, ValueError):
        return default


# 落库 tag 的写入通路：必须经 tag-rule 校验，禁止直写 user_tag
TAG_WRITE_VIA = "tag_rule"
TAG_FORBIDDEN_PREFIXES = ("user_tag", "userTag", "contact_field:")


def validate_tags(tags) -> tuple:
    """返回 (tags, warnings)。禁止直写 user_tag 的项会被剔除并告警。"""
    ok, warn = [], []
    for t in _as_list(tags):
        s = str(t)
        if any(s.lower().startswith(p.lower()) for p in TAG_FORBIDDEN_PREFIXES):
            warn.append(f"tag '{s}' 疑似直写 user_tag，已剔除（须走 tag-rule 校验通路）")
            continue
        ok.append(s)
    return ok, warn


# --------------------------- 归一化 ---------------------------
def _is_deferred(c: dict, cid: str, deferred_cids=None) -> tuple:
    """判断某波是否为 deferred（外部事件触发，不得到期自动发）。"""
    if c.get("deferred") is True:
        return True, "策略显式标记 deferred"
    if _as_dict(c.get("send_conditions")).get("deferred") is True:
        return True, "send_conditions.deferred=true"
    if str(_as_dict(c.get("trigger")).get("mode", "")).lower() == "event":
        return True, "trigger.mode=event（外部事件驱动，非 delay 排期）"
    if deferred_cids and cid in deferred_cids:
        return True, "spec.deferred_campaigns 指定"
    return False, ""


def normalize_campaign(c: dict, idx: int, goal_id: str = "",
                       default_segment: str = "",
                       default_locales: Optional[list] = None,
                       deferred_cids: Optional[list] = None) -> dict:
    """把 StrategySpec 里的一个 campaign 归一化成 strategy dict（供 compile/adaptive 直接吃）。"""
    c = _as_dict(c)
    cid = str(c.get("cid") or f"{goal_id or 'goal'}_c{idx + 1}")
    idx_n = idx + 1

    # ---- segment：每个 campaign 各自的分群（不再共用 goal.audience_segment）----
    seg = _as_dict(c.get("segment"))
    if not seg and isinstance(c.get("segment"), str):
        seg = {"mode": "reuse", "ref": c["segment"]}
    seg_ref = str(seg.get("ref") or default_segment or "")
    seg_mode = str(seg.get("mode") or "reuse")

    # ---- email：reuse=复用已有资产；generate=待生成（ref 可为 null）----
    email = _as_dict(c.get("email"))
    email_ref = str(email.get("ref") or "").strip()
    email_mode = str(email.get("mode") or ("reuse" if email_ref else "generate"))
    if not email_ref:
        email_ref = f"EM_{cid}_PLACEHOLDER"
    email_brief = _as_dict(email.get("brief"))
    locales = _as_list(email_brief.get("locale")) or _as_list(default_locales)

    # ---- content_variant：带 angle/headline 的实体，不再是裸序号 ----
    cv = _as_dict(c.get("content_variant"))
    cv_id = str(cv.get("id") or f"v{idx_n}")
    subject = (email_brief.get("subject") or cv.get("headline")
               or c.get("name") or "")

    # ---- landing page ----
    lp = _as_dict(c.get("landing_page"))
    if not lp and isinstance(c.get("landing_page"), str):
        lp = {"mode": "reuse", "ref": c["landing_page"]}

    # ---- 发送条件：缺字段安全缺省 ----
    sc_in = _as_dict(c.get("send_conditions"))
    sc = dict(DEFAULT_SEND_CONDITIONS)
    for k, v in sc_in.items():
        if v is not None:
            sc[k] = v
    sc["delay_hours"] = _num(sc.get("delay_hours"), DEFAULT_SEND_CONDITIONS["delay_hours"])
    sc["max_per_24h"] = _num(sc.get("max_per_24h"), DEFAULT_SEND_CONDITIONS["max_per_24h"])
    sc["max_per_7d"] = _num(sc.get("max_per_7d"), DEFAULT_SEND_CONDITIONS["max_per_7d"])

    tags, tag_warnings = validate_tags(c.get("tags_to_write"))
    if not tags:
        tags = [f"wave_{idx_n}"]
    deferred, deferred_reason = _is_deferred(c, cid, deferred_cids)

    return {
        # 身份
        "cid": cid,
        "wave_id": f"wave_{idx_n}",
        "variant_id": cv_id,
        "campaign_name": c.get("name") or f"[Agent] {cid}",
        "strategy_source": "agent_spec",
        "intent": "promo",
        "counts_toward_promo_cap": True,
        # 分群（每个 campaign 独立）
        "segment": seg_ref,
        "segment_mode": seg_mode,
        "segment_note": seg.get("note", "") or "",
        # 邮件资产
        "email_ref": email_ref,
        "email_mode": email_mode,
        "email_pending": email_mode != "reuse",
        "email_brief": email_brief or None,
        "email_followup_ref": f"EM_{cid}_FOLLOWUP_PLACEHOLDER",
        "subject": subject,
        "followup_subject": "提醒：" + (subject or cid),
        # 内容变体（保留 int 供自适应改写 +1；实体信息另存 *_spec）
        "content_variant": _variant_int(cv_id, idx_n),
        "content_variant_spec": {
            "id": cv_id,
            "angle": cv.get("angle", "") or "",
            "headline": cv.get("headline", "") or "",
            "summary": cv.get("summary", "") or "",
        },
        # 着陆页
        "landing_page_ref": str(lp.get("ref") or ""),
        "landing_page_mode": str(lp.get("mode") or ""),
        "landing_page_note": lp.get("note", "") or "",
        "landing_page_url": str(lp.get("url") or ""),
        # 发送条件 / 落库
        "send_conditions": sc,
        "tags_to_write": tags,
        # 决策依据（给审批人看）
        "rationale": c.get("rationale", "") or "",
        "evidence": c.get("evidence", "") or "",
        "success_criteria": _as_dict(c.get("success_criteria")) or None,
        "locales": locales,
        # 进入/退出/转人工判定（Agent 写的运营规则，只读展示）
        "judgment": c.get("judgment", "") or "",
        # deferred：外部事件触发的波次，不得到期自动发送，需运营启用
        "deferred": deferred,
        "deferred_reason": deferred_reason,
        "deferred_enable_condition": c.get("deferred_enable_condition", "") or "",
        "trigger": _as_dict(c.get("trigger")) or None,
        "tag_triggers": _as_list(c.get("tag_triggers")) or None,
        "tag_warnings": tag_warnings,
    }


def strategies_from_spec(spec: dict, goal=None) -> list:
    """StrategySpec dict → promo campaign 的 strategy dict 列表（service_sequences 不算 campaign）。"""
    spec = _as_dict(spec)
    default_segment = getattr(goal, "audience_segment", "") or ""
    goal_id = str(spec.get("goal_id") or getattr(goal, "goal_id", "") or "")
    default_locales = _as_list(spec.get("locale"))
    campaigns = _as_list(spec.get("campaigns"))
    deferred_cids = _as_list(spec.get("deferred_campaigns"))
    return [
        normalize_campaign(c, i, goal_id=goal_id,
                           default_segment=default_segment,
                           default_locales=default_locales,
                           deferred_cids=deferred_cids)
        for i, c in enumerate(campaigns)
    ]


def normalize_service_sequence(s: dict, idx: int = 0, goal_id: str = "") -> dict:
    """
    归一化一条 service 序列（登记确认件等服务性/交易性触达）。
    与 promo 的关键差异：
      - intent=service → 编译时不注入 promo 频次闸门 / 锚点仲裁
      - 豁免 suppress_promo / comm_freeze / promo 频次硬顶
      - 事件驱动（trigger.mode=event），不配 segment、不按 delay 排期
    """
    s = _as_dict(s)
    sid = str(s.get("sid") or s.get("cid") or f"{goal_id or 'goal'}_svc{idx + 1}")
    trig = _as_dict(s.get("trigger"))
    email = _as_dict(s.get("email"))
    email_ref = str(email.get("ref") or "").strip() or f"EM_{sid}_PLACEHOLDER"
    email_mode = str(email.get("mode") or ("reuse" if email.get("ref") else "generate"))
    email_brief = _as_dict(email.get("brief"))
    cv = _as_dict(s.get("content_variant"))
    cv_id = str(cv.get("id") or f"svc_v{idx + 1}")
    subject = (email_brief.get("subject") or cv.get("headline") or s.get("name") or "")
    tags, tag_warnings = validate_tags(s.get("tags_to_write"))
    timing = _as_dict(s.get("timing"))
    # service：不占 promo 配额、不设频次硬顶、免打扰按 Agent 声明豁免
    sc = {
        "delay_hours": _num(trig.get("delay_hours"), 0),
        "max_per_24h": None if s.get("counts_toward_promo_cap") is False else _num(
            s.get("max_per_24h"), None),
        "max_per_7d": None if s.get("counts_toward_promo_cap") is False else _num(
            s.get("max_per_7d"), None),
        "quiet_hours": None,
        "quiet_hours_exempt": bool(s.get("quiet_hours_exempt", trig.get("mode") == "event")),
        "quiet_hours_note": s.get("quiet_hours_note", "") or "",
        "send_within_minutes": _num(s.get("send_within_minutes"),
                                    _num(timing.get("send_within_minutes"), None)),
        "note": "service/transactional：豁免 promo 频次硬顶，不占 S 池，不计入每人 3 触上限",
    }
    exemptions = dict(_as_dict(s.get("exemptions")))
    if s.get("exempt_from_promo_suppression"):
        exemptions.setdefault("suppress_promo", "豁免（Agent 显式声明）")
    if s.get("counts_toward_promo_cap") is False:
        exemptions.setdefault("promo_frequency_cap", "不占 promo 配额")
    if sc["quiet_hours_exempt"]:
        exemptions.setdefault("quiet_hours", f"豁免（{sc['send_within_minutes'] or 0} 分钟内发出）")
    return {
        "cid": sid,
        "sid": sid,
        "wave_id": "svc",
        "variant_id": cv_id,
        "campaign_name": s.get("name") or f"[service] {sid}",
        "strategy_source": "agent_spec",
        "intent": "service",
        "segment": "",                       # service 不看 segment
        "segment_mode": "",
        "email_ref": email_ref,
        "email_mode": email_mode,
        "email_pending": email_mode != "reuse",
        "email_brief": email_brief or None,
        "email_followup_ref": None,
        "subject": subject,
        "followup_subject": None,
        "content_variant": _variant_int(cv_id, idx + 1),
        "content_variant_spec": {
            "id": cv_id,
            "angle": cv.get("angle", "") or "",
            "headline": cv.get("headline", "") or "",
            "summary": cv.get("summary", "") or "",
        },
        "landing_page_ref": str(_as_dict(s.get("landing_page")).get("ref") or ""),
        "landing_page_url": str(_as_dict(s.get("landing_page")).get("url") or ""),
        "send_conditions": sc,
        "tags_to_write": tags,
        "tag_warnings": tag_warnings,
        "trigger": trig or {"mode": "event", "delay_hours": 0},
        "timing": timing or None,
        "exemptions": exemptions,
        "counts_toward_promo_cap": s.get("counts_toward_promo_cap"),
        "content_constraints": _as_dict(s.get("content_constraints")) or None,
        "rationale": s.get("rationale", "") or "",
        "evidence": s.get("evidence", "") or "",
        "judgment": s.get("judgment", "") or "",
        "exit_note": s.get("exit", "") or "",
        "success_criteria": None,
        "deferred": False,
        "deferred_reason": "",
    }


def service_sequences_from_spec(spec: dict, goal=None) -> list:
    """StrategySpec dict → service 序列的 strategy dict 列表（与 campaigns 平级，不混编）。"""
    spec = _as_dict(spec)
    goal_id = str(spec.get("goal_id") or getattr(goal, "goal_id", "") or "")
    return [
        normalize_service_sequence(s, i, goal_id=goal_id)
        for i, s in enumerate(_as_list(spec.get("service_sequences")))
    ]


def load_strategy_spec(src: str, goal=None) -> list:
    """读入 StrategySpec（文件路径或 JSON 文本）→ promo campaign 的 strategy 列表。"""
    return strategies_from_spec(parse_strategy_spec(src), goal)


def spec_goal_defaults(spec: dict) -> dict:
    """
    抽取 StrategySpec 里属于「目标层」的字段，供 L0 Brief 合并
    （目标/窗口/KPI/预算/locale 依然可以来自运营，Agent 只补策略）。
    """
    spec = _as_dict(spec)
    out = {}
    _srcs = spec.get("_sources")
    if _srcs:
        out["_sources"] = list(_srcs)
    if spec.get("goal_id"):
        out["goal_id"] = str(spec["goal_id"])
    if spec.get("objective"):
        out["objective"] = str(spec["objective"])
    kpi = _as_dict(spec.get("kpi"))
    if kpi:
        # target 缺省 或 =0 都表示「目标值未设置」（运营尚未给 R），不是"目标为 0"
        tgt = kpi.get("target")
        unset = tgt is None or _num(tgt, 0.0) in (0, 0.0)
        out["kpi"] = {
            "type": kpi.get("metric") or "conversion_rate",
            "target": None if unset else _num(tgt, 0.15),
            "target_unset": bool(unset),
        }
        if kpi.get("note"):
            out["kpi"]["note"] = str(kpi["note"])
        if unset:
            out["kpi_target_unset"] = True
    win = _as_dict(spec.get("window"))
    if win.get("start"):
        out["start_date"] = str(win["start"])
    if win.get("end"):
        out["end_date"] = str(win["end"])
    locales = _as_list(spec.get("locale"))
    if locales:
        out["locale"] = str(locales[0])
        out["locales"] = locales
    if spec.get("budget") is not None:
        out["budget"] = _num(spec.get("budget"), 0.0)
    return out


# --------------------------- 展示辅助 ---------------------------
def email_display(s: dict) -> str:
    """reuse → 资产 ID；generate → [待生成] subject。"""
    s = s or {}
    if s.get("email_mode") == "generate" or s.get("email_pending"):
        return "[待生成] " + (s.get("subject") or "")
    ref = s.get("email_ref") or ""
    brief = s.get("email_brief") or {}
    if brief.get("subject"):
        return f"{ref} · {brief['subject']}"
    return ref


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "strategies", "example_strategy.json")
    spec = parse_strategy_spec(src)
    print(json.dumps({"goal": spec_goal_defaults(spec),
                      "strategies": strategies_from_spec(spec)},
                     ensure_ascii=False, indent=2))
