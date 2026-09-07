"""
Plan Compiler (L2) — 计划编译模块
=====================================================================
职责：把 GoalSpec（+ 一份简化的 Strategy）编译成 Mautic 可执行的「事件图提案」
      (CampaignProposal)，并【确定性地】注入治理，而非靠 LLM「记得」要加：

  1) 4 类治理节点（确定性注入，governance 标志位供复盘排除）
       - sourcemarketing.frequency_gate  频次闸门
       - anchor_arbitration              锚点仲裁（防多 campaign 同时打同一联系人）
       - guardrail                       护栏（退订/抑制名单/locale 硬合规）
       - log_channel_send                渠道记账（归因 + 合规必需落库）
  2) 9 个埋点字段（反填归因用）
       campaign_id / wave_id / variant_id / locale / channel /
       node_id / plan_hash / sent_at / contact_id
  3) mtc_* 链接参数（email CTA 调起 LP 时携带，承接转化归因）
       mtc_campaign / mtc_wave / mtc_variant / mtc_locale
  4) plan_hash（事件图规范 JSON 的 sha256）——把「审批内容」与「执行内容」绑定，
       篡改任一处节点执行引擎都会拒绝。

输出同时给出「若推送到 {base_url}/s/ 会发出的 API 调用清单」（applyAction 思路），
默认 dry-run，不污染生产 campaign #27 / #42。

仅使用 Python 标准库。
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from goal_intake import GoalSpec
from strategy_spec import TAG_WRITE_VIA

# 9 个埋点字段（反填归因用，写进每个 send/click 节点）
EMBED_FIELDS = [
    "campaign_id", "wave_id", "variant_id", "locale", "channel",
    "node_id", "plan_hash", "sent_at", "contact_id",
]

# mtc_* 链接参数（email CTA 调起 LP 时拼接）
MTC_PARAMS = ["mtc_campaign", "mtc_wave", "mtc_variant", "mtc_locale"]

# 4 类治理节点定义（确定性模板，按 GoalSpec 参数实例化）
GOVERNANCE_NODES = {
    "frequency_gate": "sourcemarketing.frequency_gate",
    "anchor_arbitration": "anchor_arbitration",
    "guardrail": "guardrail",
    "log_channel_send": "log_channel_send",
}


def _node(nid: str, ntype: str, params: dict, nxt: Optional[str] = None,
          governance: bool = False) -> dict:
    node = {
        "id": nid,
        "type": ntype,
        "params": params,
        "governance": governance,
    }
    if nxt is not None:
        node["next"] = nxt
    return node


def _inject_governance(graph: list, goal: GoalSpec, strategy: dict, campaign_id: str) -> list:
    """
    在决策入口之后、邮件发送之前，确定性插入 4 类治理节点。
    位置约定：decision(进入分群) -> guardrail -> frequency_gate
              -> anchor_arbitration -> [业务节点] -> log_channel_send。
    分群与频次闸门取自 strategy（多 campaign 各自不同），缺省回落 GoalSpec 默认值。

    ⚠️ service / transactional 序列（strategy.intent == "service"）走另一条通路：
       不注入 promo 频次闸门与锚点仲裁，并在护栏里声明豁免
       （suppress_promo / comm_freeze / promo 频次硬顶）。
       原因：登记 → suppress_promo 是 promo 规则，若套到登记确认件上，
       已登记用户会收不到确认件（交易性/服务性触达永不冻结）。
    """
    if strategy.get("intent") == "service":
        return _inject_governance_service(graph, goal, strategy, campaign_id)

    seg = strategy.get("segment") or goal.audience_segment
    sc = strategy.get("send_conditions", {}) or {}
    freq = {
        "max_per_24h": sc.get("max_per_24h", goal.frequency_cap.get("max_per_24h", 1)),
        "max_per_7d": sc.get("max_per_7d", goal.frequency_cap.get("max_per_7d", 3)),
    }
    # 入口决策节点（segment 取自 strategy → 多 campaign 各自不同）
    graph.append(_node(
        "n_decision", "decision.segment",
        {
            "segment": seg,
            "segment_ref": strategy.get("segment_ref", seg),
            "segment_mode": strategy.get("segment_mode", "reuse"),
            "locale": goal.locale,
        },
        nxt="n_guardrail",
    ))
    # 1) 护栏：硬合规，阻断退订/抑制名单/非目标 locale
    graph.append(_node(
        "n_guardrail", GOVERNANCE_NODES["guardrail"],
        {
            "honor_suppression": goal.guardrails.get("honor_suppression", True),
            "unsubscribe_burn_threshold": goal.guardrails.get("unsubscribe_burn_threshold", 0.003),
            "allow_locale": [goal.locale],
        },
        nxt="n_freq_gate", governance=True,
    ))
    # 2) 频次闸门（来自 strategy 的 send_conditions）
    graph.append(_node(
        "n_freq_gate", GOVERNANCE_NODES["frequency_gate"],
        freq, nxt="n_anchor", governance=True,
    ))
    # 3) 锚点仲裁：本 wave 内该联系人归本 campaign 所有，防并发互打
    graph.append(_node(
        "n_anchor", GOVERNANCE_NODES["anchor_arbitration"],
        {
            "campaign_id": campaign_id,
            "wave_id": strategy.get("wave_id", "wave_1"),
            "strategy": "claim_if_free",
        },
        nxt="n_email_main", governance=True,
    ))
    return graph


def _inject_governance_service(graph: list, goal: GoalSpec, strategy: dict, campaign_id: str) -> list:
    """
    service/transactional 序列的治理通路（与 promo 解耦）：
      - 入口是**事件触发**（不看 segment、不看 delay 排期）
      - 只注入 guardrail（硬退订/抑制名单/locale 仍生效）+ log_channel_send
      - **不注入** frequency_gate（不占 promo 配额）与 anchor_arbitration
      - 护栏显式声明豁免：suppress_promo / comm_freeze / promo_frequency_cap
    """
    trig = strategy.get("trigger") or {}
    graph.append(_node(
        "n_decision", "decision.event_trigger",
        {
            "trigger_mode": trig.get("mode", "event"),
            "event": trig.get("event", ""),
            "delay_hours": trig.get("delay_hours", 0),
            "note": "服务性/交易性触达：由表单提交等动作直接触发，不走 segment + delay 排期",
        },
        nxt="n_guardrail",
    ))
    sc = strategy.get("send_conditions", {}) or {}
    graph.append(_node(
        "n_guardrail", GOVERNANCE_NODES["guardrail"],
        {
            "honor_suppression": goal.guardrails.get("honor_suppression", True),
            "unsubscribe_burn_threshold": goal.guardrails.get("unsubscribe_burn_threshold", 0.003),
            "allow_locale": [goal.locale],
            "intent": "service",
            "exempt_from": ["suppress_promo", "comm_freeze", "promo_frequency_cap"],
            "exempt_note": "交易性/服务性触达永不冻结；仅硬退订/DNC 仍生效",
            # 静默窗豁免：按策略声明生效，落进事件图以便审计/审批门可驳回
            "quiet_hours_exempt": bool(sc.get("quiet_hours_exempt", False)),
            "quiet_hours_exempt_scope": (
                f"仅限用户动作即时触发、≤{sc.get('send_within_minutes')} 分钟内发出"
                if sc.get("quiet_hours_exempt") else ""),
        },
        nxt="n_email_main", governance=True,
    ))
    return graph


def compile(goal: GoalSpec, strategy: Optional[dict] = None) -> dict:
    """
    编译 GoalSpec → CampaignProposal（Mautic 可执行事件图提案）。

    strategy 可携带（多 campaign 差异化，各 campaign 独立、不共用分群）：
      cid / wave_id / variant_id / content_variant(+content_variant_spec) / segment(本波分群)
      email_ref / email_mode(reuse|generate) / email_brief / email_followup_ref
      subject / followup_subject / landing_page_ref / landing_page_url
      send_conditions { delay_hours, max_per_24h, max_per_7d, quiet_hours }
      tags_to_write [落库 tag，可驱动下游分组]
      rationale / evidence / success_criteria（给审批人看的决策依据）
    以上字段（email_ref / email_mode / brief / segment_ref / landing_page_ref /
    content_variant_spec / tags）会透传进事件图与 proposal.strategy_ref；
    治理注入与 plan_hash 计算逻辑不受影响。
    """
    strategy = strategy or {}
    campaign_id = strategy.get("cid") or goal.goal_id
    intent = strategy.get("intent", "promo")
    is_service = intent == "service"
    variant_id = strategy.get("variant_id", "v_default")
    wave_id = strategy.get("wave_id", "wave_1")
    content_variant = strategy.get("content_variant", 0)
    delay_hours = (strategy.get("send_conditions", {}) or {}).get("delay_hours", 24)
    tags = strategy.get("tags_to_write", [])

    graph: list = []
    graph = _inject_governance(graph, goal, strategy, campaign_id)

    # ---- 业务节点：email 主触达（MVP 主渠道）----
    # 着陆页 URL：优先策略指定（Agent 可在 landing_page.url 给），否则用 GoalSpec
    cta_url = strategy.get("landing_page_url") or goal.landing_page_url
    mtc_query = "&".join(
        f"{p}={val}" for p, val in zip(
            MTC_PARAMS, [campaign_id, wave_id, variant_id, goal.locale],
        )
    )
    lp_url_with_tracking = f"{cta_url}?{mtc_query}" if cta_url else ""

    # 邮件资产：优先取 Agent 策略的 email.ref（reuse=资产 ID；generate=占位 + brief）
    email_ref = strategy.get("email_ref") or f"EM_{campaign_id}_PLACEHOLDER"
    subject = strategy.get("subject") or f"{goal.objective}（变体 v{content_variant}）"
    graph.append(_node(
        "n_email_main", "email.send",
        {
            "channel": "email",
            "intent": intent,
            "email_ref": email_ref,
            "email_mode": strategy.get("email_mode", "reuse"),
            "email_brief": strategy.get("email_brief") or None,   # generate 时的生成依据
            "content_variant": content_variant,
            "content_variant_spec": strategy.get("content_variant_spec") or None,
            "content_constraints": strategy.get("content_constraints") or None,
            "subject": subject,
            "landing_page_ref": strategy.get("landing_page_ref", ""),
            "tags_to_write": list(tags),
            "cta": {
                "label": "查看详情" if is_service else "查看/购票",
                "landing_page_url": cta_url,
                "tracked_url": lp_url_with_tracking,   # 拼接 mtc_* 承接转化归因
            },
            "embed_fields": EMBED_FIELDS,
        },
        nxt="n_tag" if is_service else "n_wait",
    ))

    if is_service:
        # service/transactional：单次确认件，不做 wait/观测/分支/兜底促销 follow-up
        pass
    else:
        # ---- 等待 delay_hours 后观测（Observer，靠 mtc_* 反填，无点击 webhook）----
        graph.append(_node("n_wait", "wait", {"duration": f"{delay_hours}h"}, nxt="n_observe"))
        graph.append(_node(
            "n_observe", "observer.click",
            {
                "source": "mtc_refill",           # 靠 mtc_* 反填，非 webhook
                "metric": "landingpage_hit",
                "embed_fields": EMBED_FIELDS,
            },
            nxt="n_branch",
        ))

        # ---- 分支：点击 → LP 承接转化；未点击 → 兜底 follow-up ----
        graph.append(_node(
            "n_branch", "decision.clicked",
            {"if_true": "n_lp", "if_false": "n_followup"},
        ))
        # 点击后：着陆页承接（page.hit），归因末触
        graph.append(_node(
            "n_lp", "page.hit",
            {
                "landing_page_url": cta_url,
                "landing_page_ref": strategy.get("landing_page_ref", ""),
                "attribution": "last_touch_30d",
                "embed_fields": EMBED_FIELDS,
            },
            nxt="n_tag",
        ))
        # 未点击：兜底补发一封（仍在 email 主渠道内）
        graph.append(_node(
            "n_followup", "email.send",
            {
                "channel": "email",
                "email_ref": strategy.get("email_followup_ref", "EM_FOLLOWUP_PLACEHOLDER"),
                "subject": strategy.get("followup_subject", "提醒：" + goal.objective),
                "embed_fields": EMBED_FIELDS,
            },
            nxt="n_tag",
        ))

    # 落库 tag（可驱动下游 segment/分组）——请求③「修改落库 tag、分组」
    # 必须经 tag-rule 校验通路写入，禁止直写 user_tag
    graph.append(_node(
        "n_tag", "tag.write",
        {
            "tags": tags,
            "via": TAG_WRITE_VIA,
            "direct_user_tag_write": False,
            "note": "落库 tag，经 tag-rule 校验后写入，驱动下游分组/segment",
        },
        nxt="n_log",
    ))

    # 4) 渠道记账：每次 send 落 inventory_impression_log / lead_attribution
    graph.append(_node(
        "n_log", GOVERNANCE_NODES["log_channel_send"],
        {
            "log_table": "inventory_impression_log",
            "attribution_table": "lead_attribution",
            "channels": goal.channels,
            "tags_written": tags,
            "embed_fields": EMBED_FIELDS,
        },
        governance=True,
    ))

    # ---- 预留接口：短信（策略里占位，MVP 不启用；service 序列不预留促销短信）----
    if "sms" in goal.reserved_channels and not is_service:
        graph.append(_node(
            "n_sms_reserved", "sms.send.reserved",
            {
                "channel": "sms",
                "enabled": False,                 # MVP 不实际发送
                "note": "预留接口：待 email 闭环验证后启用",
                "embed_fields": EMBED_FIELDS,
            },
        ))

    # ---- plan_hash：事件图规范 JSON 的 sha256（不含运行时字段）----
    canonical = json.dumps(graph, ensure_ascii=False, sort_keys=True)
    plan_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    proposal = {
        "campaign": {
            "name": strategy.get("campaign_name", goal.objective),
            "goal_id": campaign_id,
            "cid": strategy.get("cid"),
            "wave_id": wave_id,
            "locale": goal.locale,
            "channels": goal.channels,
            "reserved_channels": goal.reserved_channels,
            "landing_page_url": cta_url,
            "kpi": goal.kpi,
            "start_date": goal.start_date,
            "end_date": goal.end_date,
            "strategy": strategy,
        },
        "graph": graph,
        "tracking": {
            "embed_fields": EMBED_FIELDS,
            "mtc_params": dict(zip(MTC_PARAMS, [campaign_id, wave_id, variant_id, goal.locale])),
        },
        "governance_injected": True,
        "plan_hash": plan_hash,
        "goal": goal.to_dict(),
        # 策略要点透传（供驾驶舱/审批人查看；不参与 plan_hash 计算）
        "strategy_ref": {
            "cid": strategy.get("cid"),
            "source": strategy.get("strategy_source", "default"),
            "rationale": strategy.get("rationale", "") or "",
            "evidence": strategy.get("evidence", "") or "",
            "segment_ref": strategy.get("segment") or goal.audience_segment,
            "segment_mode": strategy.get("segment_mode", "reuse"),
            "email_ref": email_ref,
            "email_mode": strategy.get("email_mode", "reuse"),
            "email_pending": bool(strategy.get("email_pending")),
            "email_brief": strategy.get("email_brief") or None,
            "content_variant": content_variant,
            "content_variant_spec": strategy.get("content_variant_spec") or None,
            "landing_page_ref": strategy.get("landing_page_ref", ""),
            "tags_to_write": list(tags),
            "success_criteria": strategy.get("success_criteria") or None,
            "intent": intent,
            "deferred": bool(strategy.get("deferred")),
            "trigger": strategy.get("trigger") or None,
            "governance_exemptions": strategy.get("exemptions") or None,
            "content_constraints": strategy.get("content_constraints") or None,
            "judgment": strategy.get("judgment", "") or "",
        },
        "approval": None,
        "deployed": False,
        "api_calls": _build_api_calls(campaign_id, plan_hash, graph),
    }
    return proposal


def _build_api_calls(campaign_id: str, plan_hash: str, graph: list) -> list:
    """
    给出「若推送到 {base_url}/s/ 会发出的 Mautic API 调用」。
    注意（合并规格附录 B/C）：
      - 更新类路由走 /api/v2
      - 事件图不可经普通 API 改，须走 applyAction
      - 频次/锚点/护栏/记账节点由执行引擎在运行时消费，不依赖 LLM 记忆
    """
    return [
        {
            "method": "POST",
            "path": "/s/api/v2/campaigns/new",
            "body": {
                "name": campaign_id,
                "isPublished": False,          # 默认下线，避免误触生产
            },
            "desc": "创建 campaign（默认 is_published=0）",
        },
        {
            "method": "POST",
            "path": f"/s/api/v2/campaigns/<id>/applyAction",
            "body": {
                "action": "importEventGraph",
                "plan_hash": plan_hash,
                "graph": graph,
            },
            "desc": "经 applyAction 写入事件图（唯一可写路径）",
        },
        {
            "method": "POST",
            "path": "/s/api/v2/campaigns/<id>/edit",
            "body": {"isPublished": True},
            "desc": "审批通过后(Gate)再上线——PoC dry-run 不执行",
        },
    ]


def dump_proposal(proposal: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(proposal, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    from goal_intake import parse_brief
    spec = parse_brief({
        "objective": "demo compile",
        "audience_segment": "SEG_DEMO",
        "landing_page_url": "http://localhost:8080/s/demo-lp",
    })
    p = compile(spec)
    print(json.dumps(p, ensure_ascii=False, indent=2))
