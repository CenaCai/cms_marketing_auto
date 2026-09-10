"""
audience_map.py — 画像包内容/视觉参数（仓库内单一事实源）
=====================================================================
职责：把「画像包 → 文案方向 / 落地页配色及设计方向 / 配图方向 / CTA / 调性 /
      频次 / 静默窗」做成仓库内可被 Python 强制校验与注入的唯一数据源。

背景：
  原先 AudienceContentMap 只存在于专家包缓存目录，仓库里没有。后果是
  cockpit 提示词里「频次/静默窗/调性/CTA 必须沿用该包 strategy」这条约束
  **既无数据也无校验**，纯靠 LLM 去一张不存在的表查。本模块读取落库后的
  `references/audience-content-map.json`，让 strategy_spec / plan_compiler /
  校验器都能拿到真实数值。

设计约束（下游 worker 依赖，勿改语义）：
  1. JSON 里 packages 是 **list**，get_package 内部按 code 建索引，对外签名不变；
  2. 未知 code / None / 空 → 回退 GENERIC，永不返回 None；
  3. 字段缺失 → 抛 AudienceMapError（清晰异常，绝不静默返回 None/空值）；
     文件整体缺失或损坏时则回落到内置 _SAFE_FALLBACK（保证进程可用）。
  4. 6 个包对同一 API 返回结构完全一致的对象。

仅使用 Python 标准库。
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(HERE, "references", "audience-content-map.json")

FALLBACK_CODE = "GENERIC"

# ===== 每个包必须存在且非空的字段（缺失即抛 AudienceMapError） =====
REQUIRED_PACKAGE_KEYS = ("code", "label_zh", "match", "strategy")
REQUIRED_STRATEGY_KEYS = (
    "frequency", "quiet_hours", "send_window", "levers", "forbidden_phrases",
    "tone", "visual", "content_direction", "cta_templates", "subject_examples",
)
REQUIRED_VISUAL_KEYS = ("summary", "palette", "design_direction", "imagery")
REQUIRED_PALETTE_KEYS = ("primary", "secondary", "accent", "bg", "text")
REQUIRED_CONTENT_DIRECTION_KEYS = ("angles", "claims", "hero_points")


class AudienceMapError(RuntimeError):
    """画像包数据不完整时抛出（字段缺失 / 类型不对 / 空值）。"""


# 文件整体缺失或损坏时的最后兜底（字段齐全，与 JSON 里 GENERIC 保持一致）
_SAFE_FALLBACK = {
    "packages": [{
        "code": FALLBACK_CODE,
        "label_zh": "通用兜底",
        "label": "通用兜底",
        "is_fallback": True,
        "match": {},
        "strategy": {
            "frequency": {"max_per_24h": 1, "max_per_7d": 2},
            "quiet_hours": "22:00-09:00",
            "send_window": ["19:00-21:00"],
            "levers": ["中性价值", "不过度修饰"],
            "forbidden_phrases": ["限时", "秒杀", "拼团", "刺激", "上头"],
            "tone": "客观、温和、不带强烈情绪。≤150字",
            "visual": {
                "summary": "中性色彩 + 通用实景图 / 单一 CTA",
                "palette": {"primary": "#37474F", "secondary": "#546E7A",
                            "accent": "#78909C", "bg": "#FAFAFA", "text": "#263238"},
                "design_direction": "中性配色 + 通用实景图；标准单列布局（标题 + 正文 + 单一 CTA）；无强视觉风格倾向，保证可读性优先。",
                "imagery": "通用实景图（目的地 / 场景），中性色彩；不使用强风格化素材与促销贴片。",
            },
            "content_direction": {
                "angles": ["中性价值", "不过度修饰"],
                "claims": ["{目的地} 活动邀请"],
                "hero_points": [
                    "首屏一句客观事实陈述（≤150字，不带强烈情绪）",
                    "中性列举 2-3 条通用卖点，不过度修饰",
                    "单一 CTA：查看详情 / 了解活动",
                ],
            },
            "cta_templates": ["查看详情", "了解活动"],
            "subject_examples": ["{目的地} 活动邀请"],
        },
    }],
    "scoring": {
        "threshold": 0.6,
        "default_weights": {"age": 0.20, "gender": 0.10, "income": 0.25,
                            "education": 0.15, "industry": 0.15,
                            "source": 0.10, "region": 0.05},
        "field_buckets": {},
    },
}

_CACHE = None


# --------------------------- 读取 ---------------------------
def load_map() -> dict:
    """读取并缓存完整 JSON；文件缺失/损坏时返回内置兜底结构（不抛异常）。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        with open(MAP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("packages"), list):
            data = _SAFE_FALLBACK
    except Exception:  # noqa: BLE001 文件不可用时退回内置兜底，保证进程不崩
        data = _SAFE_FALLBACK
    _CACHE = data
    return _CACHE


def reload_map() -> dict:
    """强制重读（测试或文件更新后使用）。"""
    global _CACHE
    _CACHE = None
    return load_map()


def _index() -> dict:
    """packages(list) → {code: package} 索引；对小写/空格容错。"""
    idx = {}
    for p in load_map().get("packages") or []:
        if isinstance(p, dict) and p.get("code"):
            idx[str(p["code"]).strip().upper()] = p
    return idx


def package_codes() -> list:
    """所有画像包 code 列表（JSON 顺序）；无数据时至少含 GENERIC。"""
    codes = [p.get("code") for p in load_map().get("packages") or []
             if isinstance(p, dict) and p.get("code")]
    return codes or [FALLBACK_CODE]


def thresholds() -> dict:
    """打分阈值与默认权重（来自 JSON scoring 段）。"""
    sc = load_map().get("scoring") or {}
    return {
        "threshold": sc.get("threshold", 0.6),
        "default_weights": sc.get("default_weights") or {},
        "field_buckets": sc.get("field_buckets") or {},
    }


# --------------------------- 校验 ---------------------------
def _require(cond, msg: str):
    """条件不成立即抛清晰异常（绝不静默返回 None）。"""
    if not cond:
        raise AudienceMapError(msg)


def _require_keys(obj, keys, where):
    _require(isinstance(obj, dict), f"{where} 缺失或不是对象")
    for k in keys:
        _require(k in obj, f"{where} 缺少字段 {k!r}")
        _require(obj[k] not in (None, "", [], {}), f"{where}.{k} 为空")


def validate_packages() -> dict:
    """校验全部画像包字段完整性；返回 {code: [错误]}，有错则抛 AudienceMapError。"""
    pkgs = load_map().get("packages") or []
    _require(pkgs, "references/audience-content-map.json 里没有任何画像包")
    errors = {}
    for p in pkgs:
        code = p.get("code") if isinstance(p, dict) else None
        where = f"package[{code or '?'}]"
        errs = []
        for k in REQUIRED_PACKAGE_KEYS:
            if k not in p or p[k] in (None, "", [], {}):
                # match 允许为空 dict（DORMANT / GENERIC 由规则命中）
                if k == "match":
                    continue
                errs.append(f"{where} 缺少或空字段 {k!r}")
        st = p.get("strategy") if isinstance(p, dict) else None
        if not isinstance(st, dict):
            errs.append(f"{where}.strategy 缺失或不是对象")
        else:
            for k in REQUIRED_STRATEGY_KEYS:
                if k not in st or st[k] in (None, "", [], {}):
                    errs.append(f"{where}.strategy.{k} 缺失或空")
            freq = st.get("frequency")
            if not isinstance(freq, dict) or freq.get("max_per_24h") is None or freq.get("max_per_7d") is None:
                errs.append(f"{where}.strategy.frequency 需要 max_per_24h / max_per_7d")
            vis = st.get("visual")
            if not isinstance(vis, dict):
                errs.append(f"{where}.strategy.visual 必须是对象（含 palette/design_direction/imagery）")
            else:
                for k in REQUIRED_VISUAL_KEYS:
                    if not vis.get(k):
                        errs.append(f"{where}.strategy.visual.{k} 缺失或空")
                pal = vis.get("palette")
                if not isinstance(pal, dict) or any(not pal.get(k) for k in REQUIRED_PALETTE_KEYS):
                    errs.append(f"{where}.strategy.visual.palette 需要 {list(REQUIRED_PALETTE_KEYS)}")
            cd = st.get("content_direction")
            if not isinstance(cd, dict):
                errs.append(f"{where}.strategy.content_direction 必须是对象（含 angles/claims/hero_points）")
            else:
                for k in REQUIRED_CONTENT_DIRECTION_KEYS:
                    if not cd.get(k):
                        errs.append(f"{where}.strategy.content_direction.{k} 缺失或空")
        if errs:
            errors[code or "?"] = errs
    if errors:
        detail = "; ".join(msg for msgs in errors.values() for msg in msgs)
        raise AudienceMapError(f"audience-content-map.json 字段不完整：{detail}")
    return {}


# --------------------------- 取包 ---------------------------
def _find(code):
    code = str(code or "").strip().upper()   # 非字符串入参（如 123）也要安全回落，不能抛异常
    return _index().get(code) if code else None


def get_package(code: str = None) -> dict:
    """按 code 取包（内部按 code 索引 packages list）。

    - 未知 code / None / 空 / 非字符串 → 回退 GENERIC，永不返回 None；
    - 返回副本（避免调用方污染缓存）；同时提供 label 与 label_zh
      （JSON 原始键是 label_zh，下游统一读 label）。
    """
    pkg = _find(code)
    if pkg is None:
        pkg = _find(FALLBACK_CODE)
    if pkg is None:                       # 连 GENERIC 都没有 → 内置兜底
        out = dict(_SAFE_FALLBACK["packages"][0])
    else:
        out = dict(pkg)
    out.setdefault("label", out.get("label_zh") or FALLBACK_CODE)
    return out


def require_package(code: str = None) -> dict:
    """严格版 get_package：code 必须真实存在（未知 code 直接抛异常）。"""
    pkg = _find(code)
    _require(pkg is not None, f"未知画像包 code={code!r}；可用：{package_codes()}")
    out = dict(pkg)
    out.setdefault("label", out.get("label_zh") or FALLBACK_CODE)
    return out


def strategy_for(code: str = None) -> dict:
    """取该包的 strategy；字段缺失抛 AudienceMapError（不静默回退、不返回 None）。"""
    pkg = get_package(code)
    where = f"package[{pkg.get('code')}].strategy"
    st = pkg.get("strategy")
    _require(isinstance(st, dict), f"{where} 缺失或不是对象")
    _require_keys(st, REQUIRED_STRATEGY_KEYS, where)
    freq = st["frequency"]
    _require(isinstance(freq, dict) and freq.get("max_per_24h") is not None
             and freq.get("max_per_7d") is not None,
             f"{where}.frequency 需要 max_per_24h / max_per_7d")
    out = dict(st)
    out["frequency"] = dict(freq)
    return out


def label_for(code: str = None) -> str:
    """包中文名（JSON 里的键是 label_zh）。"""
    return get_package(code).get("label_zh") or FALLBACK_CODE


# --------------------------- 内容 / 视觉方向 ---------------------------
def content_direction(code: str = None) -> dict:
    """
    文案方向：
      levers / tone / forbidden_phrases / cta_templates / subject_examples（兼容旧调用方）
      angles（内容角度=levers）/ claims（主张示例=subject_examples）/ hero_points（首屏要点）
    """
    st = strategy_for(code)
    where = f"package[{get_package(code).get('code')}].strategy.content_direction"
    cd = st["content_direction"]
    _require_keys(cd, REQUIRED_CONTENT_DIRECTION_KEYS, where)
    return {
        "levers": list(st["levers"]),
        "tone": st["tone"],
        "forbidden_phrases": list(st["forbidden_phrases"]),
        "cta_templates": list(st["cta_templates"]),
        "subject_examples": list(st["subject_examples"]),
        "angles": list(cd["angles"]),
        "claims": list(cd["claims"]),
        "hero_points": list(cd["hero_points"]),
    }


def visual_direction(code: str = None) -> dict:
    """
    落地页配色及设计方向：
      visual（画面调性描述）/ palette（配色 token）/ design_direction（设计方向）
      / imagery（配图方向）
    """
    st = strategy_for(code)
    where = f"package[{get_package(code).get('code')}].strategy.visual"
    vis = st["visual"]
    _require(isinstance(vis, dict), f"{where} 必须是对象（含 palette/design_direction/imagery）")
    _require_keys(vis, REQUIRED_VISUAL_KEYS, where)
    pal = vis["palette"]
    _require(isinstance(pal, dict) and all(pal.get(k) for k in REQUIRED_PALETTE_KEYS),
             f"{where}.palette 需要 {list(REQUIRED_PALETTE_KEYS)}")
    return {
        "visual": vis["summary"],
        "palette": dict(pal),
        "design_direction": vis["design_direction"],
        "imagery": vis["imagery"],
    }


def send_defaults(code: str = None) -> dict:
    """频次 / 静默窗 / 触达时段的画像包默认值（供 send_conditions 兜底）。"""
    st = strategy_for(code)
    return {
        "max_per_24h": st["frequency"]["max_per_24h"],
        "max_per_7d": st["frequency"]["max_per_7d"],
        "quiet_hours": st["quiet_hours"],
        "send_window": list(st["send_window"]),
    }


if __name__ == "__main__":
    import sys
    validate_packages()
    code = sys.argv[1] if len(sys.argv) > 1 else "HNW_FAMILY"
    print(json.dumps({
        "codes": package_codes(),
        "thresholds": thresholds(),
        "content_direction": content_direction(code),
        "visual_direction": visual_direction(code),
        "send_defaults": send_defaults(code),
    }, ensure_ascii=False, indent=2))
