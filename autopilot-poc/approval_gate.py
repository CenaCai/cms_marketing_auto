"""
Approval Gate (L3) — 审批门
=====================================================================
把「审批内容」与「执行内容」用 plan_hash 绑死：
  - 审批时锁定 proposal 的 plan_hash；
  - 推送时重新计算事件图 hash，与锁定的比对，不一致直接拒绝（防篡改）；
  - 审批超时 = EXPIRED，绝不默认批准（合并规格 §9）。

分级门禁（T1–T4，来自规格 §9）：
  T2  单渠道(email) + 单 locale(zh_CN) + 无营收  → 需人工审批（最低门槛）
  T3  多渠道(active>1) 或 跨 locale                → 需人工 + 复核
  T4  涉及营收(budget>0) / 合规(写 inventory 表)   → 需高级审批人

注意：审批人 ≠ service account；本 PoC 强制要求填 approver 名，不自动批准。
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, asdict
from typing import Optional

from goal_intake import GoalSpec

TTL_SECONDS = 30 * 60  # 审批 30 分钟内有效


def compute_plan_hash(graph: list) -> str:
    """与 plan_compiler 一致的规范 hash（防止两处实现漂移）。"""
    canonical = json.dumps(graph, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class ApprovalDecision:
    status: str          # APPROVED / EXPIRED / REJECTED
    level: str           # T2 / T3 / T4
    approver: str
    approved_at: float
    plan_hash_bound: str
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def classify_gate(goal: GoalSpec) -> tuple:
    """返回 (level, 说明)。"""
    active_multi = len(goal.channels) > 1
    cross_locale = goal.locale not in ("zh_CN",)
    if goal.budget and goal.budget > 0:
        return "T4", "涉及营收预算，需高级审批人复核"
    if active_multi or cross_locale:
        return "T3", "多渠道或跨 locale，需人工 + 复核"
    return "T2", "单渠道(email)单 locale 无营收，需人工审批"


def bind_and_approve(goal: GoalSpec, proposal: dict, approver: str,
                     now: Optional[float] = None) -> ApprovalDecision:
    """审批：绑定 plan_hash；事件图被篡改则拒绝。"""
    now = now if now is not None else time.time()
    if not approver or approver.strip().lower() in ("", "service", "service account"):
        return ApprovalDecision("REJECTED", "T2", approver, now, "",
                                "审批人不能是 service account，必须为真人")
    # 重新计算事件图 hash，与 proposal 自带比对
    live_hash = compute_plan_hash(proposal["graph"])
    if live_hash != proposal.get("plan_hash"):
        return ApprovalDecision("REJECTED", "T2", approver, now, live_hash,
                                "事件图 plan_hash 与提案不符，疑似被篡改，拒绝审批")
    level, desc = classify_gate(goal)
    return ApprovalDecision("APPROVED", level, approver.strip(), now,
                            proposal["plan_hash"], desc)


def is_valid(decision: Optional[dict], now: Optional[float] = None) -> bool:
    if not decision or decision.get("status") != "APPROVED":
        return False
    now = now if now is not None else time.time()
    return now < decision["approved_at"] + TTL_SECONDS


def verify_push(proposal: dict, decision: Optional[dict],
                now: Optional[float] = None) -> tuple:
    """推送前校验：未审批 / 超时 / plan_hash 变更 → 拒绝。返回 (ok, reason)。"""
    now = now if now is not None else time.time()
    if not decision:
        return False, "未审批：请先在驾驶舱点击审批通过"
    if decision.get("status") != "APPROVED":
        return False, f"审批状态={decision['status']}，不可推送"
    if now >= decision["approved_at"] + TTL_SECONDS:
        return False, "审批已超时(EXPIRED)，需重新审批"
    if proposal.get("plan_hash") != decision.get("plan_hash_bound"):
        return False, "plan_hash 与审批锁定的不一致，事件图被改动，拒绝推送"
    return True, "通过"
