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
import re
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


# =====================================================================
# 策略规格驱动的「分叉 / 分支终点 / 阶段升降级 / 主流程终点」
# =====================================================================
# 分叉有几个、每个分叉判断什么、每个分支终点是什么（tag/阶段/分组/邮件/落地页/表单）、
# 阶段怎么升降级、主流程在哪里收口 —— 全部由 StrategySpec 声明（strategy_spec 已归一化），
# topology.py 只给「一条旅程的形状」，不再由代码模板硬编码分支。
#
# 条件信号 → 事件图决策节点类型（Mautic 侧都能落成真实 decision 事件）：
#   email.click  → decision.clicked      → Mautic email.click（已有）、
#   email.open   → decision.opened       → Mautic email.open
#   page.hit     → decision.page_hit     → Mautic page.pagehit
#   form.submit  → decision.form_submit  → Mautic form.submit
#   未知信号      → decision.generic      → 回落已有的通用决策 email.click，并记 warning
_SIGNAL_ALIASES = {
    "click": "email.click", "clicked": "email.click",
    "open": "email.open", "opened": "email.open",
    "hit": "page.hit", "pagehit": "page.hit", "page": "page.hit", "lp": "page.hit",
    "submit": "form.submit", "form": "form.submit",
}
_SIGNAL_DECISION = {
    "email.click": "decision.clicked",
    "email.open": "decision.opened",
    "page.hit": "decision.page_hit",
    "form.submit": "decision.form_submit",
}
GENERIC_DECISION_TYPE = "decision.generic"

# 终点字段 → 节点类型；_ENDPOINT_ORDER 即发射顺序（tag → 阶段 → 分组 → 邮件 → 落地页 → 表单）
_ENDPOINT_ORDER = ("tags", "stage", "segment", "email", "landing_page", "form")
_ENDPOINT_NODE_TYPES = {
    "tags": "tag.write",
    "stage": "stage.change",
    "segment": "segment.change",
    "email": "email.send",
    "landing_page": "page.hit",
    "form": "form.submit",
}
BRANCH_ENDPOINT = "branch_endpoint"
MAIN_ENDPOINT = "main_endpoint"


def _safe_id(raw, default: str = "b") -> str:
    """branch id → 可用作节点 id 后缀的安全串（中文/空格/符号 → _）。"""
    s = re.sub(r"[^0-9A-Za-z_]+", "_", str(raw or "").strip()).strip("_")
    return s or default


def _signal_decision(signal) -> tuple:
    """条件信号 → (决策节点类型, 是否已知信号)。未知信号 → 通用决策 + False（调用方记 warning）。"""
    s = str(signal or "").strip().lower().replace("_", ".").replace("-", ".")
    s = _SIGNAL_ALIASES.get(s, s)
    if s in _SIGNAL_DECISION:
        return _SIGNAL_DECISION[s], True
    return GENERIC_DECISION_TYPE, False


def _endpoint_fields(endpoint) -> dict:
    """终点 dict → 结构化字段（缺字段安全缺省；terminal 单独取）。"""
    ep = endpoint if isinstance(endpoint, dict) else {}
    out = {k: None for k in _ENDPOINT_ORDER}
    tags = ep.get("tags")
    if isinstance(tags, (list, tuple)):
        out["tags"] = [str(t) for t in tags if str(t or "").strip()]
    elif tags not in (None, ""):
        out["tags"] = [str(tags)]
    else:
        out["tags"] = []
    for k in ("stage", "segment", "email", "landing_page", "form"):
        v = ep.get(k)
        out[k] = str(v).strip() if v not in (None, "") else None
    out["terminal"] = bool(ep.get("terminal"))
    return out


def _endpoint_has_content(fields: dict) -> bool:
    """终点是否真的声明了内容（有内容才发射节点，避免老 spec 的默认空终点改变事件图）。"""
    return any(fields.get(k) for k in _ENDPOINT_ORDER)


def _endpoint_nodes(prefix: str, fields: dict, source: str, branch_id=None) -> list:
    """
    终点字段 → 节点列表（按 tags → stage → segment → email → landing_page → form 顺序，
    用 next 串联；末端 next 留给调用方按 terminal 决定）。prefix 决定节点 id，保证分支间不撞。
    """
    nodes: list = []

    def add(suffix: str, ntype: str, params: dict):
        nid = f"{prefix}_{suffix}"
        if nodes:
            nodes[-1]["next"] = nid
        p = dict(params)
        p["endpoint"] = source
        if branch_id is not None:
            p["branch_id"] = branch_id
        nodes.append(_node(nid, ntype, p))

    if fields.get("tags"):
        add("tag", _ENDPOINT_NODE_TYPES["tags"], {
            "tags": list(fields["tags"]),
            "via": TAG_WRITE_VIA,
            "direct_user_tag_write": False,
            "note": "分支/主流程终点落库 tag（经 tag-rule 校验通路写入）",
        })
    if fields.get("stage"):
        add("stage", _ENDPOINT_NODE_TYPES["stage"], {
            "stage": fields["stage"],
            "note": "终点阶段：策略声明的是阶段名，Mautic 需 stage_id，故仅在事件图审计（不落 Mautic 事件）",
        })
    if fields.get("segment"):
        add("seg", _ENDPOINT_NODE_TYPES["segment"], {
            "segment": fields["segment"],
            "action": "add",
            "note": "终点分组：策略声明的是分组 ref，Mautic 需 segment_id，故仅在事件图审计",
        })
    if fields.get("email"):
        add("email", _ENDPOINT_NODE_TYPES["email"], {
            "channel": "email",
            "email_ref": fields["email"],
            "email_mode": "reuse",
            "embed_fields": EMBED_FIELDS,
        })
    if fields.get("landing_page"):
        add("lp", _ENDPOINT_NODE_TYPES["landing_page"], {
            "landing_page_ref": fields["landing_page"],
            "attribution": "last_touch_30d",
            "embed_fields": EMBED_FIELDS,
        })
    if fields.get("form"):
        add("form", _ENDPOINT_NODE_TYPES["form"], {
            "form_ref": fields["form"],
            "embed_fields": EMBED_FIELDS,
        })
    return nodes


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


# =====================================================================
# Campaign 命名合成：Mautic 后台默认显示 cid（c1/c2），运营看不出业务含义。
# 这里按「活动名 - 波次意图 - 票种」三段式合成结构化名，让 Mautic 列表/搜索可用业务语言。
# 例：goal_name=「新春labubu演唱会」, subject=「新春labubu演唱会-预热早鸟」, idx=0
#   → 「新春labubu演唱会-预热-早鸟票」
# =====================================================================
def _strip_goal_prefix(name: str) -> str:
    """去前缀修饰词，让活动名聚焦活动本身（去掉年份/前缀空格）。"""
    name = (name or "").strip()
    name = re.sub(r"^20\d{2}\s*年?\s*", "", name).strip()
    name = re.sub(r"^20\d{2}\s+", "", name).strip()
    name = re.sub(r"^Q[1-4]\s*", "", name, flags=re.IGNORECASE).strip()
    return name


def _extract_goal_name(goal) -> str:
    """活动名（goal_name 字段优先，否则从 objective 的「」/『」/""/"" 内抓）。"""
    if hasattr(goal, "to_dict"):
        gd = goal.to_dict()
    elif isinstance(goal, dict):
        gd = goal
    else:
        gd = {}
    name = (gd.get("goal_name") or "").strip()
    if not name:
        obj = gd.get("objective", "") or ""
        m = re.search(r'[「『""](.+?)[」』""]', obj)
        if m:
            name = m.group(1).strip()
        else:
            name = re.sub(r"\s+", "", obj)[:20]
    name = _strip_goal_prefix(name)
    return name or "活动"


def _classify_wave_intent(subject: str, idx: int) -> str:
    """从 subject 关键词 + wave 序号推断波次意图的中文标签。"""
    s = subject or ""
    sl = s.lower()
    if "预热" in s or "warmup" in sl:
        return "预热"
    if "提醒" in s or "兜底" in s or "补发" in s or "remind" in sl:
        return "提醒"
    if "VIP" in s.upper() or "vip" in sl:
        return "VIP推送"
    if "最后" in s or "末班" in s or "lastchance" in sl:
        return "末班车"
    if "开演" in s or "入场" in s:
        return "开演提醒"
    if "常规" in s or "主推" in s or "broad" in sl:
        return "主推"
    if "退订" in s or "关怀" in s or "winback" in sl or "唤醒" in s:
        return "唤醒"
    if "确认" in s or "receipt" in sl:
        return "确认"
    # 兜底按序号
    defaults = {1: "开场", 2: "跟进", 3: "主推", 4: "末班车"}
    return defaults.get(idx + 1, f"第{idx + 1}波")


def _extract_variant_label(strategy: dict, subject: str) -> str:
    """票种/变体：discount 比例 → 早鸟票；subject 关键词 → 早鸟票/VIP票/套票/现场票/折扣票/免费票；兜底 → 普通票。"""
    discount = strategy.get("discount") or {}
    cv_spec = strategy.get("content_variant_spec") or {}
    angle = (cv_spec.get("angle") or "").lower()
    sl = (subject or "").lower()
    if discount.get("enabled") and (discount.get("pct") or 0):
        pct = int(discount["pct"])
        if pct >= 20:
            return f"{pct}折早鸟票"
        if pct >= 10:
            return f"{pct}折折扣票"
        if pct > 0:
            return f"{pct}折轻折扣票"
        return "折扣票"
    if "早鸟" in (subject or ""):
        return "早鸟票"
    if "VIP" in (subject or "").upper() or "vip" in angle:
        return "VIP票"
    if "套票" in (subject or ""):
        return "套票"
    if "现场" in (subject or ""):
        return "现场票"
    if "免费" in (subject or "") or "free" in sl:
        return "免费票"
    if "折扣" in (subject or "") or "discount" in sl:
        return "折扣票"
    return "普通票"


def _compose_campaign_name(goal, strategy: dict, idx: int) -> str:
    """
    按「活动名 - 波次意图 - 票种」三段式合成 Mautic campaign 名（结构化、可读、可搜索）。

    入参：goal（GoalSpec 或 dict）、strategy（campaign strategy dict）、idx（0-based campaign 序号）
    返回：例 "新春labubu演唱会-预热-早鸟票"
    """
    goal_name = _extract_goal_name(goal)
    subject = (strategy.get("subject") or strategy.get("campaign_name") or "")
    wave_label = _classify_wave_intent(subject, idx)
    variant_label = _extract_variant_label(strategy, subject)
    parts = [goal_name, wave_label]
    if variant_label:
        parts.append(variant_label)
    # Mautic name 上限 191 字符，截断
    full = "-".join(parts)
    return full[:191]


def _wave_idx(strategy: dict) -> int:
    """从 strategy.wave_id（如 wave_3）解出 0-based 序号；解不出取 0。"""
    wid = (strategy.get("wave_id") or "wave_1")
    m = re.match(r"wave_(\d+)", wid)
    if m:
        return max(0, int(m.group(1)) - 1)
    # 退化：从 cid (c1/c2) 解
    cid = (strategy.get("cid") or "")
    m = re.search(r"c(\d+)", cid)
    if m:
        return max(0, int(m.group(1)) - 1)
    return 0


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

    策略规格声明的结构（strategy_spec 归一化后）会真正变成事件图节点：
      branches[]       → N 个分叉决策节点（signal 决定决策类型），按声明顺序串成
                         if/elif 阶梯；每个分支的 endpoint 变成该分支的终点节点
      stage_rules[]    → 阶段升降级节点（带 when 条件与 direction）
      main_endpoint    → 主流程终点节点 + 终点判断（judgment）
      window           → 约束/标注 campaign 起止日
    这些键缺失/为空时（老 spec），事件图、plan_hash、mautic_events 与改动前逐字节一致。
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
    discount = strategy.get("discount")   # 策略折扣（是否发、发多少比例）——内容本体，来自意图识别

    # ---- 策略规格声明的 分叉 / 阶段升降级 / 主流程终点（缺省为空 → 事件图与旧行为完全一致）----
    branches = [b for b in (strategy.get("branches") or []) if isinstance(b, dict)]
    stage_rules = [r for r in (strategy.get("stage_rules") or []) if isinstance(r, dict)]
    main_ep_raw = strategy.get("main_endpoint") if isinstance(strategy.get("main_endpoint"), dict) else None
    main_fields = _endpoint_fields(main_ep_raw)
    main_judgment = (main_ep_raw or {}).get("judgment") if isinstance(main_ep_raw, dict) else None
    main_used = _endpoint_has_content(main_fields) or bool(main_judgment)
    warnings: list = []

    # 分叉节点 id（按声明顺序，串成 if/elif 阶梯：命中 → 该分支终点；未命中 → 下一个分叉）
    fork_ids: list = []
    fork_plans: list = []
    for i, br in enumerate(branches):
        bid = str(br.get("id") or f"b{i + 1}")
        nid = f"n_fork_{_safe_id(bid, f'b{i + 1}')}"
        dup = 1
        while nid in fork_ids:
            dup += 1
            nid = f"n_fork_{_safe_id(bid, f'b{i + 1}')}_{dup}"
        fork_ids.append(nid)
        fork_plans.append((bid, nid, br))

    # 主流程尾部链：n_tag → [阶段升降级...] → [主流程终点判断] → [主流程终点...] → n_log
    stage_rule_ids = [f"n_stage_rule_{i + 1}" for i in range(len(stage_rules))]
    main_judge_id = "n_main_judge" if main_judgment else None
    main_ep_nodes: list = []
    if main_used:
        main_ep_nodes = _endpoint_nodes("n_main_ep", main_fields, MAIN_ENDPOINT)
        if main_ep_nodes and not main_fields.get("terminal"):
            main_ep_nodes[-1]["next"] = "n_log"
    main_ep_entry = main_ep_nodes[0]["id"] if main_ep_nodes else None
    tail_entry = (stage_rule_ids[0] if stage_rule_ids
                  else (main_judge_id or (main_ep_entry or "n_log")))

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
    # 折扣反映进邮件主题（策略内容本体：发什么比例折扣）
    if isinstance(discount, dict) and discount.get("enabled") and discount.get("pct") \
            and "OFF" not in subject:
        subject = f"{subject}（{int(discount['pct'])}% OFF）"
        strategy["subject"] = subject   # 写回策略 dict，保证下游展示/重编译一致
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
            "discount": discount,   # 折扣策略随邮件节点落库（审批人可见）
            "landing_page_ref": strategy.get("landing_page_ref", ""),
            "tags_to_write": list(tags),
            "cta": {
                "label": "查看详情" if is_service else "查看/购票",
                "landing_page_url": cta_url,
                "tracked_url": lp_url_with_tracking,   # 拼接 mtc_* 承接转化归因
            },
            "embed_fields": EMBED_FIELDS,
        },
        nxt=(fork_ids[0] if fork_ids else ("n_tag" if is_service else "n_wait")),
    ))

    if is_service:
        # service/transactional：单次确认件，不做 wait/观测/兜底促销 follow-up
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
            nxt=(fork_ids[0] if fork_ids else "n_branch"),
        ))

        if branches:
            # ---- 规格声明的分叉：N 个分支 = N 个决策节点，按声明顺序串成 if/elif 阶梯 ----
            # 命中 → 该分支终点（tag/阶段/分组/邮件/落地页/表单）；未命中 → 下一个分叉；
            # 全部未命中 → 汇入主流程尾部（n_tag）。terminal=True 的分支到此为止。
            for i, (bid, nid, br) in enumerate(fork_plans):
                cond = br.get("condition") if isinstance(br.get("condition"), dict) else {}
                ntype, known = _signal_decision(cond.get("signal"))
                if not known:
                    warnings.append(
                        f"分支 '{bid}' 的信号 '{cond.get('signal')}' 无对应决策节点，"
                        f"已回落通用决策（{GENERIC_DECISION_TYPE}）")
                fields = _endpoint_fields(br.get("endpoint"))
                ep_nodes = _endpoint_nodes(nid, fields, BRANCH_ENDPOINT, branch_id=bid)
                if ep_nodes and not fields.get("terminal"):
                    ep_nodes[-1]["next"] = "n_tag"      # 非终点分支：汇入公共落库 + 记账
                params = {
                    "signal": cond.get("signal"),
                    "op": cond.get("op") or "exists",
                    "value": cond.get("value") if cond.get("value") is not None else True,
                    "branch_id": bid,
                    "branch_type": br.get("type") or "condition",
                    "if_true": ep_nodes[0]["id"] if ep_nodes else "n_tag",
                    "if_false": fork_ids[i + 1] if i + 1 < len(fork_ids) else "n_tag",
                }
                if br.get("next"):
                    # 分支声明的下游延续（campaign 级 cid，非本图节点 id，故只记录不连线）
                    params["next"] = str(br["next"]).strip()
                    params["next_kind"] = "campaign_cid"
                if not known:
                    params["fallback"] = True
                graph.append(_node(nid, ntype, params))
                graph.extend(ep_nodes)
        else:
            # ---- 无声明分叉：沿用基础路径模板的点击分支（点击 → LP 承接；未点击 → 兜底补发）----
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
        nxt=tail_entry,
    ))

    # ---- 阶段升降级（策略规格声明）：n_tag → 规则1 → … → 规则N → 主流程终点/记账 ----
    for i, rule in enumerate(stage_rules):
        when = rule.get("when") if isinstance(rule.get("when"), dict) else {}
        nxt_id = (stage_rule_ids[i + 1] if i + 1 < len(stage_rule_ids)
                  else (main_judge_id or (main_ep_entry or "n_log")))
        graph.append(_node(
            stage_rule_ids[i], "stage.change",
            {
                "from": rule.get("from"),
                "to": rule.get("to"),
                "when": when or None,
                "direction": rule.get("direction") or "up",   # up=升级 / down=降级（审计可查）
                "note": "阶段升降级（策略规格声明）",
            },
            nxt=nxt_id,
        ))

    # ---- 主流程终点判断：命中 → 主流程终点；未命中 → 记账结束 ----
    if main_judge_id:
        jtype, jknown = _signal_decision(
            main_judgment.get("signal") if isinstance(main_judgment, dict) else None)
        if not jknown and isinstance(main_judgment, dict):
            warnings.append(
                f"主流程终点判断的信号 '{main_judgment.get('signal')}' 无对应决策节点，"
                f"已回落通用决策（{GENERIC_DECISION_TYPE}）")
        jcond = main_judgment if isinstance(main_judgment, dict) else {}
        graph.append(_node(
            main_judge_id, jtype,
            {
                "signal": jcond.get("signal"),
                "op": jcond.get("op") or "exists",
                "value": jcond.get("value") if jcond.get("value") is not None else True,
                "endpoint": MAIN_ENDPOINT,
                "if_true": main_ep_entry or "n_log",
                "if_false": "n_log",
                "note": "主流程终点判断（策略规格声明的收口条件）",
            },
        ))

    # ---- 主流程终点节点（terminal=True → 事件图在此收口，不再接业务节点）----
    graph.extend(main_ep_nodes)

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

    # ---- 活动周期：策略声明的 window 优先于 GoalSpec 起止日（未声明则完全沿用旧行为）----
    window = strategy.get("window") if isinstance(strategy.get("window"), dict) else None
    start_date = goal.start_date
    end_date = goal.end_date
    if window:
        if window.get("start"):
            start_date = str(window["start"])
        if window.get("end"):
            end_date = str(window["end"])

    proposal = {
        "campaign": {
            # 结构化中文名（活动名-波次意图-票种）替代内部 cid 作为 Mautic 显示名
            "name": _compose_campaign_name(goal, strategy, _wave_idx(strategy)),
            "goal_id": campaign_id,
            "cid": strategy.get("cid"),
            "wave_id": wave_id,
            "locale": goal.locale,
            "channels": goal.channels,
            "reserved_channels": goal.reserved_channels,
            "landing_page_url": cta_url,
            "kpi": goal.kpi,
            "start_date": start_date,
            "end_date": end_date,
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
            "discount": discount,
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
    }
    if window:
        proposal["campaign"]["window"] = window
        proposal["campaign"]["window_source"] = "strategy_spec"
    if warnings:
        # 只在真的有降级/回落时才有这个键（老 spec 的 proposal 结构与旧行为逐字节一致）
        proposal["compile_warnings"] = warnings

    # ---- Mautic 7 期望的 payload：events + canvasSettings（分开发，含 parent/child 连线）----
    # 这样经 campaign API 写入后，canvas 会出现连线、campaign_events.parent 会被正确设置，
    # 流程才能真正按 parent/child 链执行（旧版只发 importEventGraph+graph，Mautic 7 忽略连线）。
    mautic = to_mautic_events(graph, strategy)
    proposal["mautic_events"] = mautic["events"]
    proposal["mautic_canvas"] = mautic["canvasSettings"]
    proposal["mautic_lists"] = mautic.get("lists")
    proposal["api_calls"] = _build_api_calls(campaign_id, plan_hash, graph, mautic)
    return proposal


# =====================================================================
# PoC 事件图 → Mautic 7 events + canvasSettings 转换器
# =====================================================================
# Mautic 7 CampaignApiController::preSaveEntity 要求：
#   1) POST/PUT 必须带非空 events；
#   2) 必须带 lists 或 forms 作为 lead source；
#   3) 连线由 canvasSettings.connections（sourceId/targetId/anchors.source）驱动，
#      CampaignModel::setEvents() 据此设置 campaign_events.parent，从而建立执行链。
#
# PoC 的治理/观测节点（frequency_gate / anchor_arbitration / guardrail / log_channel_send /
# observer.click / page.hit / decision.segment 等）在 Mautic 没有原生等价物。
# 实测这些节点落地成 lead.field_value「无害透传」条件后，既不做真实治理、又污染画布、
# 还误导运营以为有治理在跑。故统一映射为 None——纯透传，resolve 直接穿过、不生成 Mautic 事件：
#   - 真实可执行的事件只有 email.send / email.click 决策 / lead.changetags；
#   - 治理概念仍保留在 proposal.graph（供审批/复盘），但不落到 Mautic 画布。
# 纯透传节点（wait 计时、observer.click 观测）同样不单独建事件，并入下一个真实事件：
#   wait 的 duration 成为下一事件的 triggerInterval；observer.click 并入 email.click 决策。
_MAUTIC_TYPE = {
    "email.send": "email.send",
    "tag.write": "lead.changetags",
    "guardrail": None,                              # 治理节点：Mautic 无原生护栏事件 → 不生成事件（纯透传，resolve 穿过）
    "frequency_gate": None,                         # 治理节点：无原生频次闸门 → 不生成事件
    "anchor_arbitration": None,                     # 治理节点：无原生锚点仲裁 → 不生成事件
    "log_channel_send": None,                       # 治理节点：无原生渠道记账 → 不生成事件
    "page.hit": None,                               # 观测节点：点击归因走 channel_url_trackables，不建 campaign 事件
    "decision.segment": None,                       # 进入分群门 → 不生成事件（真实分群走 campaign lists source）
    "decision.event_trigger": None,                 # 事件触发入口 → 不生成事件
    "decision.clicked": "email.click",             # 点击分支 → 成为 email.click 决策
    "observer.click": None,                         # 并入 email.click 决策
    "wait": None,                                   # 计时并入下一事件 triggerInterval
    "sms.send.reserved": None,                      # 预留/禁用 → 跳过
    # ---- 策略规格声明的分叉/终点（StrategySpec 分支真正落到 Mautic 的部分）----
    # 这四个决策在本机 Mautic 都是原生 decision（EmailBundle/PageBundle/FormBundle 注册），
    # 且 properties 空列表 = 不限制具体邮件/页面/表单（applyToAny），不会因缺资产 ID 而 500。
    "decision.opened": "email.open",               # email.open（打开邮件？）
    "decision.page_hit": "page.pagehit",           # page.pagehit（访问落地页？）
    "decision.form_submit": "form.submit",         # form.submit（提交表单？）
    "decision.generic": "email.click",             # 未知信号 → 回落已验证可用的通用决策
    # 阶段/分组/表单终点：策略声明的是「名称/ref」，Mautic 需要 stage_id / segment_id，
    # 暂无名称→ID 解析通路，故不落 Mautic 事件（留在事件图审计，避免写出坏动作）。
    "stage.change": None,
    "segment.change": None,
    "form.submit": None,
}

# Mautic 7 Event.eventType（setEvents 经 ChannelExtractor::setChannel 依赖它，缺失会 500）
_EVENT_TYPE = {
    "email.send": "action",
    "email.click": "decision",
    "email.open": "decision",
    "page.pagehit": "decision",
    "form.submit": "decision",
    "lead.changetags": "action",
    "lead.dnc": "action",
    "lead.field_value": "condition",
}


def to_mautic_events(graph: list, strategy: Optional[dict] = None) -> dict:
    """
    把 PoC 事件图编译成 Mautic 7 期望的 payload：
      {
        "events":        [ {id:newN, type, name, properties, triggerMode, ...}, ... ],
        "canvasSettings": { "nodes": [...], "connections": [ {sourceId,targetId,anchors} ] },
        "lists":         [ {id: <segment_id>} ] | None
      }
    分支（decision.clicked 的 if_true/if_false）映射为 email.click 决策的 yes/no 锚点；
    汇聚节点（如 n_tag 同时被 yes/no 两路到达）会按父实例复制，确保每条路径都能触发。
    """
    strategy = strategy or {}
    nodes = {n["id"]: n for n in graph}

    def mtype(n):
        return _MAUTIC_TYPE.get(n.get("type"))

    def resolve(start_id):
        """沿 next/if_true/if_false 穿过透传节点，返回第一个真实事件节点 id 与累计等待小时数。"""
        cid = start_id
        interval = 0
        seen = set()
        while cid and cid not in seen:
            seen.add(cid)
            n = nodes.get(cid)
            if n is None:
                return (None, interval)
            if mtype(n) is not None:
                return (cid, interval)
            if n.get("type") == "wait":
                dur = (n.get("params") or {}).get("duration", "")
                m = re.match(r"(\d+)\s*h", str(dur))
                if m:
                    interval = int(m.group(1))
            cid = n.get("next")
        return (None, interval)

    def successors(n):
        out = []
        p = n.get("params") or {}
        if "if_true" in p or "if_false" in p:
            if p.get("if_true"):
                rt, iv = resolve(p["if_true"])
                if rt:
                    out.append((rt, "yes", iv))
            if p.get("if_false"):
                rt, iv = resolve(p["if_false"])
                if rt:
                    out.append((rt, "no", iv))
        elif n.get("next"):
            rt, iv = resolve(n.get("next"))
            if rt:
                out.append((rt, None, iv))
        return out

    main_email_ref = strategy.get("email_ref") or "0"

    def _email_id(ref):
        try:
            return int(str(ref))
        except Exception:
            return 0

    def _props(n, t):
        p = n.get("params") or {}
        if t == "email.send":
            return {
                "email": _email_id(p.get("email_ref", main_email_ref)),
                "email_type": "transactional",
                "attempts": 3,
                "priority": 2,
            }
        if t == "lead.changetags":
            return {"add_tags": list(p.get("tags") or []), "remove_tags": []}
        if t == "lead.dnc":
            return {"channels": ["email"], "reason": None}
        if t == "email.click":
            return {"email": _email_id(main_email_ref), "urls": {"list": []}}
        if t == "email.open":
            return {"email": _email_id(main_email_ref)}
        if t == "page.pagehit":
            # 空 pages = 不限制具体页面（PageBundle: applyToAny）；缺 key 会报 undefined index
            return {"pages": []}
        if t == "form.submit":
            # 空 forms = 任意表单（FormBundle 只在非空时才比对）；key 必须存在
            return {"forms": []}
        # 无害透传（lead.field_value）：校验 email 非空，不改动联系人数据
        return {"field": "email", "operator": "!empty", "value": ""}

    def _name(n, t):
        p = n.get("params") or {}
        if t == "email.send":
            return f"发送邮件：{p.get('subject') or n['id']}"
        if t == "lead.changetags":
            return f"打标签：{p.get('tags') or []}"
        if t == "lead.dnc":
            return "护栏：退订/抑制校验"
        if t == "email.click":
            return "决策：是否点击"
        if t == "email.open":
            return "决策：是否打开"
        if t == "page.pagehit":
            return "决策：是否访问页面"
        if t == "form.submit":
            return "决策：是否提交表单"
        return f"{n.get('type')}（治理/观测）"

    events: list = []
    canvas_nodes: list = []
    connections: list = []
    instances: dict = {}        # (node_id, parent_sig) -> temp_id
    children_map: dict = {}     # temp_id -> [child temp_id]
    order = [0]

    def emit(node_id, parent_temp_id, anchor, interval, lane):
        key = (node_id, parent_temp_id)
        if key in instances:
            return instances[key]
        n = nodes[node_id]
        t = mtype(n)
        order[0] += 1
        tid = f"new{order[0]}"
        instances[key] = tid
        # —— 严格对齐 Mautic 7 CampaignApiControllerFunctionalTest::testCreateNewCampaign 的 201 payload ——
        # 缺 eventType / order / children / parent / decisionPath 或误用 triggerUnit、position:{x,y}、
        # anchors.target!='top' 都会触发 setEvents/setChannel 内部 500。
        ev = {
            "id": tid,
            "name": _name(n, t),
            "description": _name(n, t),
            "type": t,
            "eventType": _EVENT_TYPE.get(t, "action"),
            "order": order[0],
            "properties": _props(n, t),
            "triggerInterval": interval if (interval and interval > 0) else 0,
            "triggerIntervalUnit": "H" if (interval and interval > 0) else None,
            "triggerMode": "interval" if (interval and interval > 0) else None,
            "children": [],
            "parent": parent_temp_id,
            "decisionPath": anchor,
        }
        events.append(ev)
        canvas_nodes.append({
            "id": tid,
            "positionX": str(order[0] * 200),
            "positionY": str(lane * 160 + 40),
        })
        if parent_temp_id is not None:
            # anchors.source 约定（取自生产 campaign #27 实测）：
            #   决策分支 → "yes"/"no"；顺序（非决策 action/condition→子） → "bottom"；
            #   lead source → "leadsource"。
            # ⚠️ 不能为 null：setCanvasSettings() 对 anchors.source=null 会走重建分支并
            #    执行 null['endpoint'] → PHP fatal → HTTP 500（这是之前全量 500 的根因）。
            src_anchor = anchor if anchor in ("yes", "no") else "bottom"
            connections.append({
                "sourceId": parent_temp_id,
                "targetId": tid,
                "anchors": {"source": src_anchor, "target": "top"},
            })
            children_map.setdefault(parent_temp_id, []).append(tid)
        for (succ, sa, iv) in successors(n):
            child_lane = lane
            if sa == "yes":
                child_lane = 0
            elif sa == "no":
                child_lane = 2
            emit(succ, tid, sa, iv, child_lane)
        return tid

    # 入度（仅统计从真实节点出发的边），用于识别根节点
    indeg = {nid: 0 for nid in nodes}
    for nid, n in nodes.items():
        if mtype(n) is None:
            continue
        for (succ, _, _) in successors(n):
            indeg[succ] = indeg.get(succ, 0) + 1
    for nid in nodes:
        if mtype(nodes[nid]) is not None and indeg.get(nid, 0) == 0:
            emit(nid, None, None, 0, 1)

    # 反填 children（Mautic 期望 events[].children 为子事件 temp id 列表）
    for ev in events:
        ev["children"] = children_map.get(ev["id"], [])

    lists = None
    seg_id = strategy.get("segment_id")
    if seg_id:
        try:
            lists = [{"id": int(seg_id)}]
        except Exception:
            lists = None

    # 若提供了 segment source，把 lists 连到根事件（anchors.source='leadsource' 让 setEvents 跳过）
    if lists:
        target_ids = {c["targetId"] for c in connections}
        for cn in canvas_nodes:
            if cn["id"] not in target_ids:
                connections.append({
                    "sourceId": "lists",
                    "targetId": cn["id"],
                    "anchors": {"source": "leadsource", "target": "top"},
                })

    return {
        "events": events,
        "canvasSettings": {"nodes": canvas_nodes, "connections": connections},
        "lists": lists,
    }


def _build_api_calls(campaign_id: str, plan_hash: str, graph: list, mautic: Optional[dict] = None) -> list:
    """
    给出「若推送到 {base_url}/s/ 会发出的 Mautic API 调用」。
    注意（合并规格附录 B/C + Mautic 7 实测）：
      - 更新类路由走 /api/v2
      - Mautic 7 的 campaign 创建/编辑 API 直接在 body 里接收 events + canvasSettings，
        并在 CampaignModel::setEvents() 里据此建立 parent/child 连线；
        importEventGraph / applyAction 在 Mautic 7 不适用（会被忽略，导致无连线）。
      - 频次/锚点/护栏/记账节点由执行引擎在运行时消费，不依赖 LLM 记忆。
    """
    mautic = mautic or {}
    events = mautic.get("events", [])
    canvas = mautic.get("canvasSettings", {})
    lists = mautic.get("lists")
    create_body = {
        "name": campaign_id,
        "isPublished": False,          # 默认下线，避免误触生产
        "events": events,
        "canvasSettings": canvas,
    }
    if lists:
        create_body["lists"] = lists
    return [
        {
            "method": "POST",
            "path": "/api/campaigns/new",
            "body": create_body,
            "desc": "创建 campaign 并写入事件图（events + canvasSettings，含 parent/child 连线）",
        },
        {
            "method": "POST",
            "path": "/api/campaigns/<id>/edit",
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
