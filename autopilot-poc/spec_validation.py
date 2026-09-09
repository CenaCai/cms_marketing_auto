"""
spec_validation.py — StrategySpec 与 Brief 基础信息的一致性校验（阻断型）
=====================================================================
场景：运营在 /brief 页面上方填基础信息（目标 / 日期 / 语言 / 约束红线 / 转化率…），
      下方粘贴 Agent（LLM/专家）产出的 StrategySpec JSON。

痛点：过去二者冲突时系统照单全收，生成出来的 Program 与运营填的东西不一致
      （例：约束里写「20:00~00:00免打扰」，Agent 填成「20:00-09:00」，
        午夜被吃掉了 9 个小时；Brief 写 zh_CN，规格里写 en_US）。

决策：**只要存在冲突，就不生成 Program**，并把每一条冲突逐项列给运营。

本模块只做「校验」，不做「修正」——所有规则 severity 均为 block，由调用方
（HTTP handler）决定如何展示。

对外 API：
    validate_spec(spec, brief, pkg_code=None) -> list[Conflict]
    format_conflicts(conflicts)               -> list[str]

约束：仅用标准库；失败即缺席（任何缺失/畸形输入都不抛异常）。
     校验器复用 strategy_spec.parse_quiet_hours（红线解析的唯一真源）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from strategy_spec import parse_quiet_hours


# ------------------------------------------------------------------ 数据结构
@dataclass
class Conflict:
    """一条冲突。field 是稳定机器键，供调用方做分组/去重/埋点。"""
    field: str          # 稳定机器键，如 "locale" / "quiet_hours" / "max_per_7d"
    spec_value: str     # 规格侧取值（已字符串化）
    brief_value: str    # Brief 侧取值（已字符串化）
    message: str        # 中文、可执行的一句话说明
    campaign: str = ""  # 逐 campaign 的冲突带 cid，否则为空串
    severity: str = "block"   # 目前所有冲突均阻断


# 字段名 → 中文标签（用于拼装消息）
LABELS = {
    "locale": "语言/地区",
    "audience_package": "人群包",
    "quiet_hours": "免打扰窗口",
    "max_per_7d": "每周发送上限",
    "max_per_24h": "每日发送上限",
    "window_start": "投放窗口开始",
    "window_end": "投放窗口结束",
    "window_order": "投放窗口顺序",
    "region_locale": "地区与语言",
    "kpi_target": "KPI 目标",
}


def _label(key: str) -> str:
    return LABELS.get(key, key)


# ------------------------------------------------------------ 防御式小工具
def _as_dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _as_list(v) -> list:
    """把入参安全转成 list：dict/str 等特殊形态一律安全退化。"""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [x for x in v]
    if isinstance(v, str):
        # "zh_CN" 或 "zh_CN, en_US"（表单里常见逗号串）
        parts = [p.strip() for p in re.split(r"[,，;；\s]+", v)]
        return [p for p in parts if p]
    return [v]


def _s(v) -> str:
    """任意值 → 字符串；None 显示为空值占位。"""
    if v is None:
        return "（未设置）"
    if isinstance(v, (list, tuple)):
        items = [str(x) for x in v if x not in (None, "")]
        return "、".join(items) if items else "（空）"
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, float):
        return ("%g" % v)
    if isinstance(v, dict):
        return "、".join(f"{k}={v[k]}" for k in v) if v else "（空）"
    return str(v)


def _num(v):
    """尽力转 float；失败返回 None。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace("%", ""))
    except Exception:
        return None


def _cid(c: dict, i: int) -> str:
    return str(c.get("cid") or c.get("id") or f"campaigns[{i}]")


def _conflicts_from(key: str, spec_value, brief_value, message: str,
                    campaign: str = "") -> Conflict:
    return Conflict(field=key, spec_value=_s(spec_value),
                    brief_value=_s(brief_value), message=message,
                    campaign=campaign)


# ------------------------------------------------------ 规则 1：locale 集合
def _locale_set(v) -> set:
    return {str(x).strip() for x in _as_list(v) if str(x).strip()}


def _rule_locale(spec: dict, brief: dict) -> list:
    sv = _locale_set(spec.get("locale"))
    bv = _locale_set(brief.get("locale"))
    # 任一侧缺失/为空 → 不比较（规格没写语言，或 Brief 没勾语言）
    if not sv or not bv:
        return []
    if sv & bv:
        return []
    return [_conflicts_from(
        "locale", sorted(sv), sorted(bv),
        f"{_label('locale')} 与 Brief 不符：规格 {'、'.join(sorted(sv))}，"
        f"Brief {'、'.join(sorted(bv))}",
    )]


# --------------------------------------------- 规则 2：audience_package 比对
def _stripped_str(v) -> str:
    """非字符串的畸形值（dict/list 等）按缺失处理，避免误判与崩溃。"""
    return v.strip() if isinstance(v, str) else ""


def _rule_audience_package(spec: dict, pkg_code) -> list:
    sp = _stripped_str(spec.get("audience_package"))
    pk = _stripped_str(pkg_code)
    if not sp or not pk or sp.casefold() == pk.casefold():
        return []
    return [_conflicts_from(
        "audience_package", sp, pk,
        f"{_label('audience_package')} 与 Brief 不一致：规格 {sp}，"
        f"Brief 按画像推断 {pk}（请改成 {pk}，或修改目标人群画像）",
    )]


# ------------------------- 规则 3：免打扰窗口（约束红线优先，逐 campaign 比对）
_QUIET_DASHES = {"~": "-", "－": "-", "—": "-", "–": "-", "〜": "-", "～": "-"}


def _norm_quiet(v) -> str:
    """归一化静默窗文本：波形线/全角横杠统一成 '-'，去所有空白。"""
    if v is None:
        return ""
    t = str(v)
    for a, b in _QUIET_DASHES.items():
        t = t.replace(a, b)
    return re.sub(r"\s+", "", t)


def _constraints_blob(brief: dict) -> str:
    """Brief 的约束文本统一转成一段 blob（支持 str / list / 多行文本）。"""
    raw = brief.get("constraints")
    parts = [str(x) for x in _as_list(raw) if str(x).strip()]
    return "；".join(parts) if parts else ""


def _rule_quiet_hours(spec: dict, brief: dict) -> list:
    expected = parse_quiet_hours(brief.get("constraints"))
    if not expected:
        return []
    exp_n = _norm_quiet(expected)
    out = []
    for i, c in enumerate(_as_list(spec.get("campaigns"))):
        c = _as_dict(c)
        if not c:
            continue
        sc = _as_dict(c.get("send_conditions"))
        got = sc.get("quiet_hours")
        cid = _cid(c, i)
        if got is None or not str(got).strip():
            out.append(_conflicts_from(
                "quiet_hours", "（未设置）", expected,
                f"{_label('quiet_hours')} 缺失，Brief 红线要求 {expected}"
                f"（请在 send_conditions 里显式声明）",
                campaign=cid))
            continue
        if _norm_quiet(got) != exp_n:
            out.append(_conflicts_from(
                "quiet_hours", got, expected,
                f"{_label('quiet_hours')} 与 Brief 红线不符：规格 {got}，"
                f"Brief 红线 {expected}",
                campaign=cid))
    return out


# ---------------------------------- 规则 4：频次硬顶（每周 / 每天，逐 campaign）
_CAP_UNITS = (
    ("max_per_7d", r"(每\s*周|每\s*週|每\s*7\s*天|每\s*七天|每\s*周内)", "每周"),
    ("max_per_24h", r"(每\s*天|每\s*日|每\s*24\s*小?时)", "每天"),
)
_STOP_CHARS = "；;。,\n\r、|"


def _cap_value(blob: str, unit_re: str):
    """在单位词后面就近取数字；遇到「至少/≥」这类下限词跳过。"""
    for m in re.finditer(unit_re, blob):
        seg = blob[m.end():m.end() + 12]
        stop = min([seg.find(ch) for ch in _STOP_CHARS if seg.find(ch) >= 0] or [len(seg)])
        seg = seg[:stop]
        if re.search(r"(至少|不少于|不低于|≥|>=)", blob[max(0, m.start() - 4):m.end()] + seg):
            continue
        num = re.search(r"(\d+(?:\.\d+)?)", seg)
        if num:
            return _num(num.group(1))
    return None


def parse_frequency_caps(constraints):
    """从约束文本里解析频次红线，返回 (每周上限, 每天上限)，取不到为 None。"""
    parts = [str(x) for x in _as_list(constraints) if str(x).strip()]
    blob = "；".join(parts)
    if not blob.strip():
        return (None, None)
    weekly = _cap_value(blob, _CAP_UNITS[0][1])
    daily = _cap_value(blob, _CAP_UNITS[1][1])
    return (weekly, daily)


def _rule_frequency(spec: dict, brief: dict) -> list:
    weekly_cap, daily_cap = parse_frequency_caps(brief.get("constraints"))
    if weekly_cap is None and daily_cap is None:
        return []
    out = []
    for i, c in enumerate(_as_list(spec.get("campaigns"))):
        c = _as_dict(c)
        if not c:
            continue
        sc = _as_dict(c.get("send_conditions"))
        cid = _cid(c, i)
        got7 = _num(sc.get("max_per_7d"))
        if weekly_cap is not None and got7 is not None and got7 > weekly_cap:
            out.append(_conflicts_from(
                "max_per_7d", got7, weekly_cap,
                f"{_label('max_per_7d')} 超出 Brief 红线：规格 {_s(got7)}，"
                f"Brief 红线 {_s(weekly_cap)}（每周≤{_s(weekly_cap)}封）",
                campaign=cid))
        got24 = _num(sc.get("max_per_24h"))
        if daily_cap is not None and got24 is not None and got24 > daily_cap:
            out.append(_conflicts_from(
                "max_per_24h", got24, daily_cap,
                f"{_label('max_per_24h')} 超出 Brief 红线：规格 {_s(got24)}，"
                f"Brief 红线 {_s(daily_cap)}（每天≤{_s(daily_cap)}封）",
                campaign=cid))
    return out


# ------------------------------------ 规则 5：投放窗口 vs Brief 活动起止日期
def _rule_window(spec: dict, brief: dict) -> list:
    w = _as_dict(spec.get("window"))
    ws = str(w.get("start") or "").strip()
    we = str(w.get("end") or "").strip()
    bs = str(brief.get("start_date") or "").strip()
    be = str(brief.get("end_date") or "").strip()
    if not ws and not we:
        return []
    out = []
    # 内部自洽：开始不应晚于结束（不依赖 Brief，永远检查）
    if ws and we and ws > we:
        out.append(_conflicts_from(
            "window_order", f"{ws} → {we}", f"开始应 ≤ 结束",
            f"{_label('window_order')} 不合法：规格 {ws} → {we}（开始晚于结束）"))
    if bs and ws and ws < bs:
        out.append(_conflicts_from(
            "window_start", ws, bs,
            f"{_label('window_start')} 早于 Brief 活动开始日：规格 {ws}，Brief {bs}"))
    if be and we and we > be:
        out.append(_conflicts_from(
            "window_end", we, be,
            f"{_label('window_end')} 晚于 Brief 活动结束日：规格 {we}，Brief {be}"))
    return out


# --------------------- 规则 6：Brief 内部矛盾 —— 地区不含中国大陆却要 zh_CN
_CN_MAINLAND = "中国大陆"


def _brief_regions(brief: dict) -> list:
    """地区可能在 audience_region，也可能在 audience_profile.region。"""
    regions = _as_list(brief.get("audience_region"))
    prof = _as_dict(brief.get("audience_profile"))
    regions = regions + _as_list(prof.get("region"))
    return [str(x).strip() for x in regions if str(x).strip()]


def _rule_region_locale(brief: dict) -> list:
    regions = _brief_regions(brief)
    locales = _locale_set(brief.get("locale"))
    # Brief 没填地区 → 无从判断，跳过
    if not regions or "zh_CN" not in locales:
        return []
    # 已包含中国大陆 → 与 zh_CN 不矛盾
    if _CN_MAINLAND in "、".join(regions):
        return []
    return [_conflicts_from(
            "region_locale", "zh_CN", "、".join(regions),
            f"{_label('region_locale')} 冲突：Brief 地区 {_s(regions)} 不含「{_CN_MAINLAND}」，"
            f"但 Brief locale 含 zh_CN（请移除 zh_CN 或补选中国大陆）",
        )]
    return []


# ---------------------------------------------- 规则 7：KPI 目标 vs 整体转化率
def _rule_kpi(spec: dict, brief: dict) -> list:
    kpi = _as_dict(spec.get("kpi"))
    target = _num(kpi.get("target"))
    if target is None:
        return []
    raw_oc = brief.get("overall_conv")
    oc_txt = str(raw_oc).strip() if raw_oc is not None else ""
    oc = _num(oc_txt) if oc_txt else None
    if oc is None:
        return []
    if abs(target - oc) <= 1e-9:
        return []
    return [_conflicts_from(
        "kpi_target", target, oc,
        f"{_label('kpi_target')} 与 Brief 整体转化率不符：规格 {_s(target)}，Brief {_s(oc)}",
    )]


# ------------------------------------------------------------------ 对外入口
def validate_spec(spec: dict, brief: dict, pkg_code: str = None) -> list:
    """
    校验 StrategySpec 是否与 Brief 基础信息一致。

    返回 Conflict 列表；一致（或 spec 为空）时返回 []。
    绝不抛异常——任何缺失/畸形字段都按「该项不校验」处理；
    例外是规则 3/4（约束红线一旦解析出来即具权威性）与规则 5 的内部自洽检查。
    """
    spec = _as_dict(spec)
    brief = _as_dict(brief)
    out = []
    for rule in (
        lambda: _rule_locale(spec, brief),
        lambda: _rule_audience_package(spec, pkg_code),
        lambda: _rule_quiet_hours(spec, brief),
        lambda: _rule_frequency(spec, brief),
        lambda: _rule_window(spec, brief),
        lambda: _rule_region_locale(brief),
        lambda: _rule_kpi(spec, brief),
    ):
        try:
            got = rule()
        except Exception as e:      # 单条规则炸了不能拖垮整份校验
            got = [Conflict(field="internal_error", spec_value=_s(type(e).__name__),
                            brief_value=_s(e),
                            message=f"校验规则执行异常：{type(e).__name__} {e}")]
        if got:
            out.extend(got)
    return out


def format_conflicts(conflicts) -> list:
    """每条冲突一行中文，供 UI 直接渲染（HTML 转义由调用方负责）。"""
    if not conflicts:
        return []
    lines = []
    for c in conflicts:
        line = c.message
        if getattr(c, "campaign", ""):
            line = f"{line}（{c.campaign}）"
        lines.append(f"· {line}")
    return lines
