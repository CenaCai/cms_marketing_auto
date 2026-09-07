"""
Goal Intake (L0) — 目标输入模块
=====================================================================
职责：把一份「营销 Brief」（自然语言来源的半结构化 JSON，或交互式输入）
      解析、校验、归一化成结构化的 GoalSpec。

GoalSpec 是下游 Plan Compiler 的唯一输入契约。
PoC 阶段所有渠道默认遵循 MVP 裁定：
  - 主渠道 channels = ["email"]           （实际触达）
  - 预留渠道 reserved_channels = ["sms"]  （策略里留接口，MVP 不发送）
  - email 内 CTA 调起 landing_page_url 承接转化

仅使用 Python 标准库，确保本地零依赖可跑。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

# MVP 渠道裁定默认值（见合并规格 v1.0 附录 D：2026-09-07 用户裁定）
DEFAULT_CHANNELS = ["email"]
DEFAULT_RESERVED_CHANNELS = ["sms"]


@dataclass
class GoalSpec:
    """结构化目标规格——Goal Intake 的产物。"""
    goal_id: str
    objective: str                                  # 营销目标（一句话）
    kpi: dict                                       # 考核指标，如 {"type":"conversion_rate","target":0.15}
    audience_segment: str                           # 目标分群（可选，可为空：由 Agent 策略按波次各自指定）
    name: str = ""                                  # 目标名称（便于阅读，非技术 key）
    locale: str = "zh_CN"                           # 语言/地区，如 zh_CN / en_US（支持双语）
    channels: list = field(default_factory=lambda: list(DEFAULT_CHANNELS))
    reserved_channels: list = field(default_factory=lambda: list(DEFAULT_RESERVED_CHANNELS))
    landing_page_url: str = ""                      # email 内 CTA 调起的着陆页
    budget: float = 0.0                             # 仅在 is_revenue=True 时有意义（与金额无关，仅审计）
    is_revenue: bool = False                        # 涉及营收/付费目标（取代 budget>0 判据）
    start_date: str = ""
    end_date: str = ""
    frequency_cap: dict = field(default_factory=dict)    # 频次闸门参数
    guardrails: dict = field(default_factory=dict)       # 护栏参数（退订阈值等）
    # 目标人群画像（来自 Brief 表单 ① 段；结构化字段，L1 专家按 audience-content-map 命中画像包）
    audience_package: str = "GENERIC"               # 选定的画像包 code；CUSTOM 时由 L1 重算
    audience_profile: dict = field(default_factory=dict)  # {age, gender, income, education, industry, source, region}
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# Brief 中允许出现的字段 → GoalSpec 字段 的映射（自然语言键也能吃）
_FIELD_ALIASES = {
    "goal_id": "goal_id",
    "id": "goal_id",
    "name": "name",
    "目标名称": "name",
    "营销活动名称": "name",
    "objective": "objective",
    "goal": "objective",
    "目标": "objective",
    "kpi": "kpi",
    "指标": "kpi",
    "audience_segment": "audience_segment",
    "segment": "audience_segment",
    "分群": "audience_segment",
    "locale": "locale",
    "语言": "locale",
    "channels": "channels",
    "渠道": "channels",
    "reserved_channels": "reserved_channels",
    "预留渠道": "reserved_channels",
    "landing_page_url": "landing_page_url",
    "landing_page": "landing_page_url",
    "着陆页": "landing_page_url",
    "budget": "budget",
    "预算": "budget",
    "is_revenue": "is_revenue",
    "is_revenue_bool": "is_revenue",
    "是否涉及营收": "is_revenue",
    "start_date": "start_date",
    "开始": "start_date",
    "end_date": "end_date",
    "结束": "end_date",
    "frequency_cap": "frequency_cap",
    "频次": "frequency_cap",
    "guardrails": "guardrails",
    "护栏": "guardrails",
    "audience_package": "audience_package",
    "画像包": "audience_package",
    "audience_profile": "audience_profile",
    "目标人群特点": "audience_profile",
    "画像": "audience_profile",
}


def _normalize(raw: dict) -> dict:
    """把任意键名（含中文/别名）归一化为 GoalSpec 字段。"""
    out: dict = {}
    for k, v in raw.items():
        # 兼容嵌套 dict（如 kpi/frequency_cap/guardrails 直接传对象）
        target = _FIELD_ALIASES.get(k)
        if target is None:
            continue
        out[target] = v
    return out


def parse_brief(raw: dict) -> GoalSpec:
    """
    解析一份 Brief dict → GoalSpec。
    做三件事：
      1. 键名归一化（支持中文键 / 别名）
      2. 缺失必填项的兜底与校验
      3. 应用 MVP 渠道裁定默认值（email 主、sms 预留）
    """
    data = _normalize(raw)

    # 必填项兜底
    if not data.get("objective"):
        raise ValueError("Brief 缺少必填项：objective（营销目标）")
    # audience_segment 改为可选：分群由 Agent 在 StrategySpec 里按波次产出，
    # L0 不再强校验（缺失时留空，由策略首波 segment.ref 兜底）。
    if not data.get("audience_segment"):
        data["audience_segment"] = ""
    data.setdefault("kpi", {"type": "conversion_rate", "target": 0.15})
    data.setdefault("locale", "zh_CN")
    data.setdefault("goal_id", "goal_" + uuid.uuid4().hex[:8])
    # 目标名称默认回退到 goal_id：未填写则用 id 值，填写则保留填写内容
    if not data.get("name"):
        data["name"] = data["goal_id"]

    # MVP 渠道裁定：未显式指定渠道时，强制 email 主 + sms 预留
    if "channels" not in data or not data["channels"]:
        data["channels"] = list(DEFAULT_CHANNELS)
    if "reserved_channels" not in data:
        data["reserved_channels"] = list(DEFAULT_RESERVED_CHANNELS)

    # 频次闸门默认：每 24h 最多 1 封、每 7d 最多 3 封
    data.setdefault("frequency_cap", {"max_per_24h": 1, "max_per_7d": 3})
    # 护栏默认：退订熔断阈值 0.3%（见合并规格 §4 分歧中取保守侧），强制尊重退订/抑制名单
    data.setdefault("guardrails", {
        "unsubscribe_burn_threshold": 0.003,
        "honor_suppression": True,
    })

    # 画像包与画像 profile：默认 GENERIC + 空 profile（运营未填时）
    data.setdefault("audience_package", "GENERIC")
    if not isinstance(data.get("audience_profile"), dict):
        data["audience_profile"] = {}
    # is_revenue 规整为 bool（表单可能传 "1"/"0"/"true"/"false"/True）
    rv = data.get("is_revenue")
    if isinstance(rv, str):
        data["is_revenue"] = rv.strip().lower() in ("1", "true", "yes", "on")
    elif rv is None:
        data["is_revenue"] = False
    else:
        data["is_revenue"] = bool(rv)
    # is_revenue=False 时清零 budget（避免误用旧值触发 T4 审批门）
    if not data["is_revenue"]:
        data["budget"] = 0.0

    return GoalSpec(**data)


def load_brief(path: str) -> dict:
    """从 JSON 文件读取一份 Brief。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def prompt_brief() -> dict:
    """交互式收集一份最小 Brief（CLI 用）。"""
    print("=== Goal Intake 交互式 Brief ===")
    raw = {
        "objective": input("营销目标（一句话）: ").strip(),
        "audience_segment": input("目标分群 (segment 别名/ID): ").strip(),
        "locale": input("语言/地区 [zh_CN]: ").strip() or "zh_CN",
        "landing_page_url": input("email 调起的着陆页 URL: ").strip(),
        "kpi_target": input("考核目标值(转化率 0~1) [0.15]: ").strip() or "0.15",
    }
    raw["kpi"] = {"type": "conversion_rate", "target": float(raw.pop("kpi_target"))}
    return raw


if __name__ == "__main__":
    # 直接运行本文件 = 演示一次 Goal Intake
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else None
    brief = load_brief(src) if src else {
        "objective": "demo", "audience_segment": "SEG_DEMO", "landing_page_url": "http://localhost:8080/s/demo-lp"
    }
    spec = parse_brief(brief)
    print(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2))
