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

      // ---- 分叉 / 终点 / 阶段升降级 / 主流程收口（规则 4）----
      "branches": [
        {
          "id": "clicked",
          "note": "点击后的处理（note 里的「打标/阶段/分组/邮件/落地页/表单」等词会参与动作判定）",
          "when": {"signal": "email.click|email.open|page.hit|form.submit",
                   "op": ">=|exists", "value": 1},
          // endpoint 列出「这个分支可用的终点类型」（候选集）。
          // ⚠️ 列了几个 ≠ 触发几个：真正触发哪个由下面 actions 决定。
          "endpoint": {
            "tags": ["clicked"],
            "stage": "engaged",           // 阶段名，由代码解析成 stage_id
            "segment": "SEG_HOT",         // 分组名/ref，解析成 segment_id（"action":"remove" = 移出）
            "email": "EM_FOLLOWUP",
            "landing_page": "LP_MAIN",
            "form": "FORM_SIGNUP",        // 表单名，解析成 form_id
            "terminal": false
          },
          // actions：Agent 判定「这次到底触发哪几个」。不写 → 代码按分支语义推断 1 个，
          // 并在 compile_warnings 里写明忽略了哪些（不会静默丢需求）。
          "actions": ["tags"],
          "next": "ucl2028_c2"           // 可选：下游 campaign 的 cid
        }
      ],
      "stage_rules": [
        {"from": "lead", "to": "mql", "when": {"signal": "form.submit"}, "direction": "up|down"}
      ],
      "main_endpoint": {
        "tags": ["converted"], "stage": "customer", "terminal": true,
        "judgment": {"signal": "page.hit", "op": ">=", "value": 2}
      }
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

from topology import journey_for_intent  # 拓扑模板：intent → 旅程骨架（仅形状，不含内容）

try:  # audience_map 由另一条线并行维护，导入失败时降级为空包（绝不因它崩掉整条策略链）
    import audience_map
except Exception:  # noqa: BLE001
    audience_map = None

# 发送条件安全缺省（Agent 少写字段时回落，不会崩）
DEFAULT_SEND_CONDITIONS = {"delay_hours": 0, "max_per_24h": 1, "max_per_7d": 3}

GENERIC_PACKAGE = "GENERIC"

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


def _synthesize_variant_spec(c: dict, campaign_name: str, discount: dict = None) -> dict:
    """策略未显式给出 content_variant（空槽）时，同步生成一个默认 v1 变体。

    变体是「与主邮件同主题、不同切入角度」的 A/B 版本，保证 campaign 流程里始终有一条
    可走的变体路径（plan_compiler 据此注入 decision.variant 路由节点）。
    角度按是否带折扣推导：带折扣 → 限时紧迫；否则 → 稀缺专属。headline/summary 从
    campaign 名与折扣推导，确定、可读、便于审批人核对。"""
    cv = _as_dict(c.get("content_variant")) if isinstance(c, dict) else {}
    if cv.get("id") and (cv.get("angle") or cv.get("headline") or cv.get("summary")):
        return cv  # 已显式提供完整变体 → 原样返回
    has_discount = bool(isinstance(discount, dict) and discount.get("enabled"))
    pct = int(discount["pct"]) if (has_discount and discount.get("pct")) else None
    angle = "限时紧迫" if has_discount else "稀缺专属"
    disc_txt = f"（{pct}% OFF 限时）" if pct else "（专属限时）"
    headline = f"{campaign_name or '活动'} · 变体 v1{disc_txt}"
    summary = ("与主邮件同主题、不同切入角度的 A/B 变体："
               f"以「{angle}」制造紧迫感促转化；variant_split 命中比例时走此变体路径。")
    return {"id": "v1", "angle": angle, "headline": headline, "summary": summary}


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


# --------------------------- 静默窗（quiet_hours）确定性提取 ---------------------------
# 约束文本里的「X:00~Y:00免打扰」是红线，必须由代码确定性解析，
# 不能信任 LLM 在 StrategySpec 里手填的 quiet_hours（曾出现「20:00~00:00免打扰」被写成
# 「20:00-09:00」——把午夜 00:00 误换成默认结束时间 09:00）。
_QH_RANGE_RE = re.compile(r"(\d{1,2})\s*:\s*(\d{2})\s*[~\-－—]\s*(\d{1,2})\s*:\s*(\d{2})")
_QH_KEYWORD_RE = re.compile(r"(免打扰|静默|不打[扰扰]|不推送|不能发|禁[发触])")


def _norm_hhmm(h: str, m: str) -> str:
    """把小时/分钟规整为 2 位；午夜保持 00:00（绝不回落到其它值）。"""
    hh = int(h) % 24
    mm = int(m) % 60
    return f"{hh:02d}:{mm:02d}"


def parse_quiet_hours(constraints) -> Optional[str]:
    """
    从约束/红线文本里确定性提取静默窗，返回 "HH:MM-HH:MM"（跨午夜用 '-' 连接，
    开始>结束表示跨午夜）。解析不到返回 None（此时回落 LLM/默认）。

    支持写法：
      - 「20:00~00:00免打扰」「22:00-09:00 免打扰」「20:00—09:00静默」
      - 「晚 20 点后不推送，次日 10 点再发」→ start=20:00 end=10:00（带「次日」才跨午夜）
      - 「X 点后不能发」且未提次日 → start=X:00 end=00:00（默认到午夜）
    """
    if not constraints:
        return None
    texts = constraints if isinstance(constraints, (list, tuple)) else [constraints]
    blob = " ； ".join(str(t) for t in texts)
    if not blob.strip():
        return None

    # 1) 直接的 HH:MM~HH:MM / HH:MM-HH:MM 区间：贴近静默窗关键词的优先采信
    for m in _QH_RANGE_RE.finditer(blob):
        seg = blob[max(0, m.start() - 8): m.end() + 8]
        if _QH_KEYWORD_RE.search(seg):
            return (f"{_norm_hhmm(m.group(1), m.group(2))}"
                    f"-{_norm_hhmm(m.group(3), m.group(4))}")
    # 纯时间区间（如用户只写「20:00~00:00」未带关键词）也接受
    m = _QH_RANGE_RE.search(blob)
    if m:
        return (f"{_norm_hhmm(m.group(1), m.group(2))}"
                f"-{_norm_hhmm(m.group(3), m.group(4))}")

    # 2) 自然语言：「X 点后不(能)发/不推送」(+ 次日/第二天/明早 Y 点)
    after = re.search(r"(\d{1,2})(?::(\d{2}))?\s*点?\s*[后以后]\s*(不[能]*发|不推送|免打扰|静默)", blob)
    if after:
        start = _norm_hhmm(after.group(1), after.group(2) or "00")
        nxt = re.search(r"(次日|第二天|隔天|明天|明早)\s*(\d{1,2})\s*点?", blob)
        end = _norm_hhmm(nxt.group(2), "00") if nxt else "00:00"
        return f"{start}-{end}"
    return None


# --------------------------- 画像包（audience package）---------------------------
# 「画像包 + 策略规划 + 属性 结合才是最终生成 program 的总策略」：
#   画像包提供 频次 / 静默窗 / 触达时段 / 文案方向 / 落地页视觉方向 / CTA 模板 的默认值，
#   策略规划（StrategySpec）显式值覆盖画像包，红线约束再覆盖策略规划。
# audience_map 可能仍在改动，所有读取都包 try/except，失败回落空值而非抛异常。
def _pkg_call(fn_name: str, code, default, with_code: bool = True):
    """安全调用 audience_map.<fn_name>(code)；不可用/异常 → default。"""
    if audience_map is None:
        return default
    try:
        out = getattr(audience_map, fn_name)(code) if with_code else getattr(audience_map, fn_name)()
    except Exception:  # noqa: BLE001
        return default
    return out if out is not None else default


def package_codes() -> list:
    """可用画像包 code 列表（audience_map 不可用时只有 GENERIC）。"""
    codes = _pkg_call("package_codes", None, [], with_code=False) or []
    return [str(c) for c in codes] or [GENERIC_PACKAGE]


def is_known_package(code) -> bool:
    code = str(code or "").strip()
    if not code:
        return False
    return code.upper() in {c.upper() for c in package_codes()}


def resolve_audience_package(spec=None, goal=None, campaign=None) -> str:
    """
    确定画像包 code。优先级：campaign 级 > spec 级 > goal 属性 > GENERIC。
    未知 code 一律回落 GENERIC（不因未知包名把整条策略打挂）。
    """
    for cand in (
        _as_dict(campaign).get("audience_package"),
        _as_dict(spec).get("audience_package"),
        getattr(goal, "audience_package", None),
    ):
        code = str(cand or "").strip()
        if code and is_known_package(code):
            return code.upper()
    return GENERIC_PACKAGE


def package_send_defaults(code) -> dict:
    """画像包默认 频次/静默窗/触达时段；取不到 → {}（回落到常量缺省）。"""
    out = _pkg_call("send_defaults", code, {}) or {}
    return out if isinstance(out, dict) else {}


def package_content(code) -> dict:
    """画像包内容方向 / 视觉方向 / CTA 模板（绑定文案与落地页设计方向）。"""
    cd = _pkg_call("content_direction", code, {}) or {}
    vd = _pkg_call("visual_direction", code, {}) or {}
    if not isinstance(cd, dict):
        cd = {}
    if not isinstance(vd, dict):
        vd = {}
    return {
        "content_direction": cd or {},
        "visual_direction": vd or {},
        "cta_templates": list(cd.get("cta_templates") or []),
    }


# --------------------------- 分支 / 终点 / 阶段规则 解析 ---------------------------
# 策略规格必须真正驱动：分叉数量、每个分叉的判断条件、每个分支的终点
# （tag / 阶段 / 分组 / 邮件 / 落地页 / 表单）、阶段升降级、主流程终点及终点判断。
# 写法宽容（LLM 手写 JSON 形态不一）：condition/when/if 等价，数组或 id→对象 都收。
_COND_KEYS = {
    "signal": ("signal", "event", "metric", "on", "key", "field"),
    "op": ("op", "operator", "cmp", "compare", "comparator"),
    "value": ("value", "threshold", "target", "threshold_value"),
}
_OP_RE = re.compile(r"^\s*([\w.\-:]+)\s*(>=|<=|==|!=|=|>|<|in\b|contains\b)?\s*(.*)$", re.I)


def _pick(d: dict, keys, default=None):
    d = _as_dict(d)
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return default


def normalize_condition(raw):
    """
    归一化判断条件 → {"signal": str, "op": str, "value": any}；无法识别 → None。
    接受：
      {"signal": "email.click", "op": ">=", "value": 1}
      {"when": {...}} / {"condition": {...}} / {"if": {...}}（外层由调用方剥掉）
      "email.click >= 1" / "email.click"（后者 op=exists, value=true）
    """
    if isinstance(raw, str):
        m = _OP_RE.match(raw)
        if not m:
            return None
        signal = m.group(1).strip()
        if not signal:
            return None
        op = (m.group(2) or "exists").strip().lower()
        if op == "=":
            op = "=="
        val = (m.group(3) or "").strip()
        if val == "":
            value = True
        else:
            try:
                value = int(val)
            except ValueError:
                try:
                    value = float(val)
                except ValueError:
                    value = val
        return {"signal": signal, "op": op, "value": value}
    raw = _as_dict(raw)
    if not raw:
        return None
    signal = _pick(raw, _COND_KEYS["signal"])
    if signal is None and set(raw) == {"op", "value"}:
        return None
    if signal is None:
        # 形如 {"email.click": {">=": 1}} / {"email.click": 1}
        for k, v in raw.items():
            if k in ("op", "operator", "value", "threshold", "target", "note", "desc"):
                continue
            if isinstance(v, dict):
                for op, vv in v.items():
                    return {"signal": str(k), "op": str(op).lower(), "value": vv}
            return {"signal": str(k), "op": ">=", "value": v}
        return None
    op = str(_pick(raw, _COND_KEYS["op"], "") or "").strip().lower()
    if not op:
        op = "exists" if _pick(raw, _COND_KEYS["value"]) is None else "=="
    elif op == "=":
        op = "=="
    value = _pick(raw, _COND_KEYS["value"])
    if value is None:
        # exists / not_exists 语义为「发生即满足」，value 缺省 True；其余比较也兜底 True
        value = True
    return {"signal": str(signal), "op": op, "value": value}


_ENDPOINT_KEYS = {
    "tags": ("tags", "tag", "tags_to_write", "write_tags", "tag_to_write"),
    "stage": ("stage", "stage_to", "to_stage", "lifecycle_stage", "stage_name"),
    "segment": ("segment", "segment_ref", "group", "list", "segment_to"),
    "email": ("email", "email_ref", "email_to"),
    "landing_page": ("landing_page", "landing_page_ref", "lp", "page", "lp_ref"),
    "form": ("form", "form_ref", "form_id"),
    "terminal": ("terminal", "is_terminal", "end", "is_end"),
    # actions：本次终点「真正要触发哪几个动作」。声明了字段 ≠ 全部触发，
    # 没写时由 plan_compiler 按分支语义推断一个。例：{"tags": [...], "stage": "x", "actions": ["tags","stage"]}
    # ⚠️ 不收 "action"：那是 segment 的 add/remove（{"segment":"X","action":"remove"}），
    #    混进来会把 "remove" 当动作名解析，导致整个终点被清空。
    "actions": ("actions", "do", "fire", "emit", "run", "触发"),
}
EMPTY_ENDPOINT = {"tags": [], "stage": None, "segment": None, "email": None,
                  "landing_page": None, "form": None, "terminal": False, "actions": [],
                  "note": "", "action": "add"}


def normalize_endpoint(raw, terminal_default: bool = False):
    """
    归一化一个终点（分支终点 / 主流程终点）→ EMPTY_ENDPOINT 同构 dict。
    字段：tags / stage / segment / email / landing_page / form / terminal。
    裸字符串按 tag 处理（策略里最常见的简写）；None/空 → 全空终点。
    """
    if raw is None or raw == "" or raw == [] or raw == {}:
        return dict(EMPTY_ENDPOINT, terminal=bool(terminal_default))
    if isinstance(raw, str):
        raw = {"tags": [raw]}
    raw = _as_dict(raw)
    if not raw:
        return dict(EMPTY_ENDPOINT, terminal=bool(terminal_default))
    out = dict(EMPTY_ENDPOINT)
    for key, aliases in _ENDPOINT_KEYS.items():
        if key in ("terminal", "actions"):
            continue
        v = _pick(raw, aliases)
        if key == "tags":
            out["tags"] = [str(t) for t in _as_list(v) if str(t or "").strip()]
        elif key in ("segment", "email", "landing_page", "form"):
            # 允许 {"segment": {"ref": "SEG_X"}} 这种带 ref 的写法
            if isinstance(v, dict):
                v = v.get("ref") or v.get("id") or v.get("name") or ""
            out[key] = str(v).strip() if v not in (None, "") else None
        else:
            out[key] = str(v).strip() if v not in (None, "") else None
    acts = _pick(raw, _ENDPOINT_KEYS["actions"])
    out["actions"] = [str(a) for a in _as_list(acts) if str(a or "").strip()] \
        if acts not in (None, "", [], {}) else []
    # note/desc 是给「该触发哪个动作」的推断提供文案线索的（也是审批人看的说明）
    out["note"] = str(_pick(raw, ("note", "desc", "description")) or "")
    # action：分组终点的 add / remove（"移出 SEG_PROMO" 也是合法终点语义）
    act = str(_pick(raw, ("action", "segment_action")) or "").strip().lower()
    out["action"] = "remove" if act in ("remove", "rm", "delete", "移出", "移除") else "add"
    term = _pick(raw, _ENDPOINT_KEYS["terminal"])
    out["terminal"] = bool(term) if term is not None else bool(terminal_default)
    return out


def normalize_branches(raw) -> list:
    """
    归一化分支（分叉）列表 → [{"id","type","condition","endpoint","next"}]
    接受：
      - 数组：[{"id": "clicked", "condition": {...}, "endpoint": {...}}]
      - id→对象：{"clicked": {"when": {...}, "endpoint": {...}}}
      - 条件简写：{"id": "opened", "when": "email.open >= 1"} / 裸字符串数组
    """
    out = []
    if isinstance(raw, dict):
        items = [(k, v) for k, v in raw.items()]
    else:
        items = [(None, v) for v in _as_list(raw)]
    for i, (key, item) in enumerate(items):
        if isinstance(item, str):
            item = {"condition": item}
        item = _as_dict(item)
        if not item and key is None:
            continue
        inner = item
        if "branch" in item and isinstance(item["branch"], dict):
            inner = item["branch"]
        bid = str(_pick(item, ("id", "bid", "branch_id", "name"), "") or key or f"b{i + 1}")
        cond_src = _pick(item, ("condition", "when", "if", "cond"))
        cond = normalize_condition(cond_src if cond_src is not None else item)
        ep_src = _pick(item, ("endpoint", "then", "to", "target", "outcome"))
        endpoint = normalize_endpoint(ep_src if ep_src is not None else inner)
        # actions 写在分支层（endpoint 的兄弟键）也算数——那是更自然的写法：
        # {"id":"clicked","actions":["tags","stage"],"endpoint":{...}}
        if not endpoint.get("actions"):
            bacts = _pick(item, _ENDPOINT_KEYS["actions"])
            if bacts not in (None, "", [], {}):
                endpoint["actions"] = [str(a) for a in _as_list(bacts) if str(a or "").strip()]
        btype = str(_pick(item, ("type", "kind"), "") or "").strip().lower()
        if btype not in ("decision", "condition"):
            btype = "condition" if cond else "decision"
        nxt = _pick(item, ("next", "goto", "next_branch"))
        if isinstance(nxt, dict):
            nxt = nxt.get("id") or nxt.get("cid") or None
        out.append({
            "id": bid,
            "type": btype,
            "condition": cond,
            "endpoint": endpoint,
            "next": str(nxt).strip() if nxt not in (None, "") else None,
            # note/label 保留：既是审批说明，也是「该触发哪个终点动作」的推断线索
            "note": str(_pick(item, ("note", "desc", "description", "label")) or ""),
        })
    return out


def normalize_stage_rules(raw) -> list:
    """
    归一化阶段升降级规则 → [{"from","to","when","direction"}]
    接受 stage_rules / stage_transitions；when/condition/if 等价；direction 缺省 "up"。
    """
    out = []
    for r in _as_list(raw):
        if isinstance(r, str):
            r = {"to": r}
        r = _as_dict(r)
        if not r:
            continue
        frm = _pick(r, ("from", "from_stage", "src", "source"))
        to = _pick(r, ("to", "to_stage", "dst", "stage", "target"))
        if isinstance(frm, dict):
            frm = frm.get("stage") or frm.get("name")
        if isinstance(to, dict):
            to = to.get("stage") or to.get("name")
        cond_src = _pick(r, ("when", "condition", "if", "cond"))
        cond = normalize_condition(cond_src if cond_src is not None else r)
        direction = str(_pick(r, ("direction", "dir"), "") or "").strip().lower()
        if direction in ("up", "upgrade", "升", "升级", "上升"):
            direction = "up"
        elif direction in ("down", "downgrade", "降", "降级", "下降"):
            direction = "down"
        else:
            direction = "up"        # 缺省升级（显式写才降级）
        out.append({
            "from": str(frm).strip() if frm not in (None, "") else None,
            "to": str(to).strip() if to not in (None, "") else None,
            "when": cond,
            "direction": direction,
        })
    return out


def normalize_main_endpoint(c: dict):
    """
    主流程终点 + 终点判断：c["main_endpoint"]（兼容 endpoint / terminal）。
    返回 EMPTY_ENDPOINT 同构 + "judgment"（条件 dict 或 None）。
    主流程终点默认 terminal=True（它是 campaign 的收口）。
    """
    c = _as_dict(c)
    src = None
    for k in ("main_endpoint", "endpoint", "terminal_endpoint", "terminal"):
        if c.get(k) is not None:
            src = c[k]
            break
    ep = normalize_endpoint(src, terminal_default=True)
    judgment = None
    if isinstance(src, dict):
        j = _pick(src, ("judgment", "judge", "when", "condition", "if", "exit_condition"))
        judgment = normalize_condition(j) if j is not None else None
    if judgment is None:
        j = c.get("main_endpoint_judgment") or c.get("endpoint_judgment")
        judgment = normalize_condition(j) if j is not None else None
    ep["judgment"] = judgment
    return ep


def normalize_window(raw) -> Optional[dict]:
    """归一化活动周期 {"start","end"}；无法识别 → None。"""
    if isinstance(raw, str):
        parts = [p.strip() for p in re.split(r"[~～\-–—/至到]+", raw) if p.strip()]
        if len(parts) >= 2:
            return {"start": parts[0], "end": parts[1]}
        if len(parts) == 1:
            return {"start": parts[0], "end": None}
        return None
    w = _as_dict(raw)
    if not w:
        return None
    start = _pick(w, ("start", "start_date", "from", "begin"))
    end = _pick(w, ("end", "end_date", "to", "until"))
    if start is None and end is None:
        return None
    return {
        "start": str(start).strip() if start not in (None, "") else None,
        "end": str(end).strip() if end not in (None, "") else None,
    }


def normalize_campaign(c: dict, idx: int, goal_id: str = "",
                       default_segment: str = "",
                       default_locales: Optional[list] = None,
                       deferred_cids: Optional[list] = None,
                       quiet_hours_override: Optional[str] = None,
                       audience_package: Optional[str] = None,
                       default_window=None,
                       spec_level: Optional[dict] = None) -> dict:
    """把 StrategySpec 里的一个 campaign 归一化成 strategy dict（供 compile/adaptive 直接吃）。

    audience_package：命中/指定的画像包 code。传入后，画像包 strategy 会为
    频次 / 静默窗 / 触达时段 / 文案方向 / 落地页视觉方向 提供**真正生效的默认值**
    （此前画像包只是提示词里的一句软约束，代码从不消费）。
    default_window：spec 层活动周期（campaign 自己没写 window 时回落到这里）。
    spec_level：spec 顶层 dict，用于读取 spec 级 branches/stage_rules/main_endpoint 兜底。
    """
    c = _as_dict(c)
    spec_level = _as_dict(spec_level)
    cid = str(c.get("cid") or f"{goal_id or 'goal'}_c{idx + 1}")
    idx_n = idx + 1
    audience_package = resolve_audience_package(spec_level, None, c) if not audience_package \
        else str(audience_package).strip().upper()
    if audience_package and not is_known_package(audience_package):
        audience_package = GENERIC_PACKAGE

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
    # 策略未显式给出（空槽）→ 同步生成默认 v1 变体，保证流程里始终有可走的变体路径。
    cv = _as_dict(c.get("content_variant"))
    if not (cv.get("id") and (cv.get("angle") or cv.get("headline") or cv.get("summary"))):
        cv = _synthesize_variant_spec(c, c.get("name") or f"[Agent] {cid}",
                                      _as_dict(c.get("discount")))
    cv_id = str(cv.get("id") or f"v{idx_n}")
    subject = (email_brief.get("subject") or cv.get("headline")
               or c.get("name") or "")

    # ---- landing page ----
    lp = _as_dict(c.get("landing_page"))
    if not lp and isinstance(c.get("landing_page"), str):
        lp = {"mode": "reuse", "ref": c["landing_page"]}

    # ---- 发送条件：优先级 规格显式值 > 画像包默认值 > 常量缺省 ----
    sc_in = _as_dict(c.get("send_conditions"))
    # 画像包默认值（频次 / 静默窗 / 触达时段）：此前画像包在代码里完全空转，
    # 这里让它成为真正生效的默认值来源。
    pkg_defaults = package_send_defaults(audience_package)
    sc = dict(DEFAULT_SEND_CONDITIONS)
    for k in ("max_per_24h", "max_per_7d", "quiet_hours"):
        if pkg_defaults.get(k) is not None:
            sc[k] = pkg_defaults[k]
    for k, v in sc_in.items():
        if v is not None:
            sc[k] = v
    # 节奏（cadence_days）：规格写了就存下来并折算成 delay_hours（仅在未显式给 delay_hours 时）
    # ——此前这类字段被完全忽略，导致「发送频次/周期」在代码里空转。
    cadence_days = sc.get("cadence_days")
    cadence_days = _num(cadence_days, None) if cadence_days not in (None, "") else None
    delay_from_cadence = False
    if cadence_days is not None and sc_in.get("delay_hours") is None:
        sc["delay_hours"] = int(cadence_days) * 24
        delay_from_cadence = True
    sc["delay_hours"] = _num(sc.get("delay_hours"), DEFAULT_SEND_CONDITIONS["delay_hours"])
    sc["max_per_24h"] = _num(sc.get("max_per_24h"), DEFAULT_SEND_CONDITIONS["max_per_24h"])
    sc["max_per_7d"] = _num(sc.get("max_per_7d"), DEFAULT_SEND_CONDITIONS["max_per_7d"])
    if cadence_days is not None:
        sc["cadence_days"] = cadence_days
    # 触达时段：规格 > 画像包
    send_window = sc_in.get("send_window") or pkg_defaults.get("send_window") or []
    if send_window:
        sc["send_window"] = send_window

    # 静默窗红线：约束文本显式给出免打扰窗口时，优先级最高（高于规格、也高于画像包）
    # （防止「20:00~00:00免打扰」被 LLM 误写成「20:00-09:00」——午夜 00:00 被换成 09:00）
    red_line_qh = bool(quiet_hours_override and not sc.get("quiet_hours_exempt"))
    if red_line_qh:
        sc["quiet_hours"] = quiet_hours_override

    # ---- 活动周期：campaign.window > spec.window ----
    window = normalize_window(c.get("window")) or normalize_window(default_window)

    # ---- 分叉 / 分支终点 / 阶段升降级 / 主流程终点（策略规格真正驱动的部分）----
    branches_raw = c.get("branches")
    if branches_raw is None:
        branches_raw = c.get("forks")
    if branches_raw is None:
        branches_raw = spec_level.get("branches")     # spec 层兜底（全 campaign 共用一套分叉）
    branches = normalize_branches(branches_raw)

    stage_raw = c.get("stage_rules")
    if stage_raw is None:
        stage_raw = c.get("stage_transitions")
    if stage_raw is None:
        stage_raw = spec_level.get("stage_rules") or spec_level.get("stage_transitions")
    stage_rules = normalize_stage_rules(stage_raw)

    main_endpoint = normalize_main_endpoint(c)
    if not _is_empty(main_endpoint.get("judgment")) or any(
            main_endpoint.get(k) for k in ("tags", "stage", "segment", "email",
                                           "landing_page", "form")):
        main_ep_src = "spec"
    else:
        main_ep_src = "default"

    # ---- 画像包内容/视觉方向：绑定文案方向与落地页设计方向 ----
    pkg_content = package_content(audience_package)
    cd_spec = _as_dict(c.get("content_direction")) or _as_dict(spec_level.get("content_direction"))
    vd_spec = _as_dict(c.get("visual_direction")) or _as_dict(spec_level.get("visual_direction"))
    cta_spec = _as_list(c.get("cta_templates")) or _as_list(spec_level.get("cta_templates"))
    content_direction = dict(pkg_content["content_direction"])
    if cd_spec:
        content_direction.update(cd_spec)
    visual_direction = dict(pkg_content["visual_direction"])
    if vd_spec:
        visual_direction.update(vd_spec)
    cta_templates = list(cta_spec) if cta_spec else list(pkg_content["cta_templates"])

    # 来源溯源：总策略 = 画像包 + 策略规划 + 属性，UI 需标注每个值来自哪一层
    def _src(key, spec_key=None):
        sk = spec_key or key
        if sk == "quiet_hours" and red_line_qh:
            return "red_line"
        if sc_in.get(sk) is not None:
            return "spec"
        if pkg_defaults.get(sk) is not None:
            return "package"
        return "default"

    from_package, from_spec, from_constraints, from_default = [], [], [], []
    provenance = {
        "audience_package": audience_package or GENERIC_PACKAGE,
        "max_per_24h": _src("max_per_24h"),
        "max_per_7d": _src("max_per_7d"),
        "quiet_hours": _src("quiet_hours"),
        "send_window": ("spec" if sc_in.get("send_window")
                        else ("package" if pkg_defaults.get("send_window") else "none")),
        "delay_hours": ("spec(cadence_days)" if delay_from_cadence else _src("delay_hours")),
        "window": "spec" if window else "none",
        "branches": "spec" if branches else "none",
        "stage_rules": "spec" if stage_rules else "none",
        "main_endpoint": main_ep_src,
        "content_direction": "spec" if cd_spec else ("package" if content_direction else "none"),
        "visual_direction": "spec" if vd_spec else ("package" if visual_direction else "none"),
        "cta_templates": "spec" if cta_spec else ("package" if cta_templates else "none"),
    }
    for k, v in provenance.items():
        if k == "audience_package":
            continue
        if v == "red_line":
            from_constraints.append(k)
        elif v.startswith("spec"):
            from_spec.append(k)
        elif v == "package":
            from_package.append(k)
        else:
            from_default.append(k)

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
        # A/B 分流比例：命中比例走变体 v1，其余走主邮件；0 表示不启用变体路径
        "variant_split": (_num(c.get("variant_split"), 0.5)
                          if _num(c.get("variant_split"), None) is not None else 0.5),
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
        # 折扣（策略本体：是否发折扣、发什么比例——来自意图识别，非硬编码）
        # 复制一份，避免 evaluate_and_replan 改写时污染源 StrategySpec
        "discount": (dict(_as_dict(c.get("discount"))) if _as_dict(c.get("discount")) else None),
        # 旅程拓扑键（promo/service），仅形状；内容由本 dict 其余字段决定
        "journey": journey_for_intent(c.get("intent") or "promo"),
        # 进入/退出/转人工判定（Agent 写的运营规则，只读展示）
        "judgment": c.get("judgment", "") or "",
        # deferred：外部事件触发的波次，不得到期自动发送，需运营启用
        "deferred": deferred,
        "deferred_reason": deferred_reason,
        "deferred_enable_condition": c.get("deferred_enable_condition", "") or "",
        "trigger": _as_dict(c.get("trigger")) or None,
        "tag_triggers": _as_list(c.get("tag_triggers")) or None,
        "tag_warnings": tag_warnings,
        # ---- 策略规格真正驱动的部分（新增，纯附加，不影响既有键）----
        # 活动周期：campaign.window > spec.window > None
        "window": window,
        # 分叉：每个 branch = 判断条件 + 该分支终点（tag/阶段/分组/邮件/落地页/表单）
        "branches": branches,
        # 阶段升降级规则：from → to，when 为触发条件
        "stage_rules": stage_rules,
        # 主流程终点及终点判断
        "main_endpoint": main_endpoint,
        # 画像包内容 / 视觉方向（绑定文案方向与落地页设计方向）
        "content_direction": content_direction,
        "visual_direction": visual_direction,
        "cta_templates": cta_templates,
        # 总策略来源溯源：每个值来自 红线 / 规格 / 画像包 / 缺省
        "_compose": {
            "package": audience_package or GENERIC_PACKAGE,
            "from_package": from_package,
            "from_spec": from_spec,
            "from_constraints": from_constraints,
            "from_default": from_default,
            "provenance": provenance,
        },
    }


def compose_final_strategy(spec: dict, goal=None, constraints=None) -> list:
    """
    最终总策略 = 画像包默认 + 策略规划（spec）+ 目标属性，按优先级合并：
      1. 红线约束（parse_quiet_hours）—— quiet_hours 永远最高
      2. 规格显式值（campaign 级 send_conditions / window / branches / endpoints / stage_rules）
      3. 画像包默认（频次 / 静默窗 / 触达时段 / 文案方向 / 视觉方向 / CTA）
      4. 代码常量（DEFAULT_SEND_CONDITIONS）/ None
    返回与 strategies_from_spec 相同的 strategy dict 列表，每条额外带 _compose 溯源。
    """
    spec = _as_dict(spec)
    default_segment = getattr(goal, "audience_segment", "") or ""
    goal_id = str(spec.get("goal_id") or getattr(goal, "goal_id", "") or "")
    default_locales = _as_list(spec.get("locale"))
    campaigns = _as_list(spec.get("campaigns"))
    deferred_cids = _as_list(spec.get("deferred_campaigns"))
    # 画像包：spec 级 > goal 属性 > GENERIC（campaign 级可再覆盖）
    pkg_code = resolve_audience_package(spec, goal)
    # 红线静默窗：约束文本优先于 LLM 手填（防止午夜被误写成 09:00）
    if constraints is None and goal is not None:
        meta = getattr(goal, "meta", None)
        constraints = (meta or {}).get("constraints") if isinstance(meta, dict) else None
    qh = parse_quiet_hours(constraints)
    spec_window = spec.get("window")
    return [
        normalize_campaign(c, i, goal_id=goal_id,
                           default_segment=default_segment,
                           default_locales=default_locales,
                           deferred_cids=deferred_cids,
                           quiet_hours_override=qh,
                           audience_package=pkg_code,
                           default_window=spec_window,
                           spec_level=spec)
        for i, c in enumerate(campaigns)
    ]


def strategies_from_spec(spec: dict, goal=None, constraints=None) -> list:
    """StrategySpec dict → promo campaign 的 strategy dict 列表（service_sequences 不算 campaign）。

    与 compose_final_strategy 同一条通路（画像包 + 规格 + 属性 合并），
    返回结构不变（仅比旧版多出 window/branches/stage_rules/main_endpoint/… 附加键）。
    """
    return compose_final_strategy(spec, goal, constraints)


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
    if not (cv.get("id") and (cv.get("angle") or cv.get("headline") or cv.get("summary"))):
        cv = _synthesize_variant_spec(s, s.get("name") or f"[service] {sid}",
                                      _as_dict(s.get("discount")))
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
        # A/B 分流比例（service 序列同样可走变体路径；默认 0.5）
        "variant_split": (_num(s.get("variant_split"), 0.5)
                          if _num(s.get("variant_split"), None) is not None else 0.5),
        "landing_page_ref": str(_as_dict(s.get("landing_page")).get("ref") or ""),
        "landing_page_url": str(_as_dict(s.get("landing_page")).get("url") or ""),
        "send_conditions": sc,
        "tags_to_write": tags,
        "tag_warnings": tag_warnings,
        "discount": (dict(_as_dict(s.get("discount"))) if _as_dict(s.get("discount")) else None),
        "journey": "service",
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
