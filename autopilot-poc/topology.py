"""
topology.py — 基础路径拓扑模板（Framework Path）
=====================================================================
「基础路径」只描述营销旅程的**核心流程形状**（阶段 + 分支锚点），
不含任何业务内容（分群 / 邮件 / 频次 / 折扣 / 落库 tag / 是否启用某分支）。
内容 100% 来自意图 + StrategySpec 实例化（见 strategy_spec.normalize_campaign）。

两个内置拓扑（与 plan_compiler.compile 的执行骨架一一对应）：
  - PROMO_JOURNEY：进入分群 → 护栏 → 频次闸门 → 锚点仲裁 → 主触达 → 观测 →
                   分支(点击?) → [承接(LP) | 兜底补发] → 落库 tag → 渠道记账
  - SERVICE_JOURNEY：事件触发 → 护栏 → 主触达 → 落库 tag → 渠道记账（无 wait/观测/促销分支）

Program 层的 campaign 组合（几个 campaign、如何分支互联）由 StrategySpec 决定，
拓扑只给出「一条旅程长什么样」的模板，绝不替策略发明内容或波次。
"""
from __future__ import annotations


PROMO_JOURNEY = {
    "id": "promo_core",
    "description": "促销旅程核心路径：分群进入 → 治理闸门 → 主触达 → 观测点击 → (承接|兜底) → 落库 → 记账",
    "stages": [
        "entry.segment",       # 进入分群门（segment 来自策略，非拓扑硬编码）
        "guardrail",           # 硬合规护栏（退订/抑制/locale）
        "frequency_gate",      # 频次闸门（max_per_24h / max_per_7d 来自策略）
        "anchor_arbitration",  # 锚点仲裁（防多 campaign 互打同一联系人）
        "primary_send",        # 主触达邮件（email/subject/LP 来自策略）
        "observe",             # 观测点击（mtc_* 反填，非 webhook）
        "branch.engaged",      # 决策：是否点击
        "convert.lp",          # 分支A：点击 → LP 承接转化
        "fallback.send",       # 分支B：未点击 → 兜底补发（可带折扣，来自策略）
        "tag.write",           # 落库 tag（驱动下游 segment/分组，来自策略）
        "log.channel_send",    # 渠道记账（归因 + 合规落库）
    ],
    "branches": {
        "branch.engaged": {"if_true": "convert.lp", "if_false": "fallback.send"},
    },
}

SERVICE_JOURNEY = {
    "id": "service_core",
    "description": "服务/交易性旅程：事件触发入口 → 护栏 → 主触达 → 落库 → 记账（无促销分支/频次闸门）",
    "stages": [
        "entry.event_trigger",  # 事件触发入口（不看 segment / delay 排期）
        "guardrail",
        "primary_send",
        "tag.write",
        "log.channel_send",
    ],
    "branches": {},
}

# 拓扑注册表：intent → 旅程模板
TOPOLOGIES = {"promo": PROMO_JOURNEY, "service": SERVICE_JOURNEY}


def journey_for_intent(intent: str) -> str:
    """intent → 拓扑键。service/transactional 走 SERVICE_JOURNEY，其余走 PROMO_JOURNEY。"""
    return "service" if str(intent).lower() in ("service", "transactional") else "promo"


def journey_stages(intent: str) -> list:
    """返回某 intent 对应的核心阶段列表（供 UI/校验展示，不含内容）。"""
    return list(TOPOLOGIES[journey_for_intent(intent)]["stages"])
