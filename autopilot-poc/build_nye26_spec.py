# -*- coding: utf-8 -*-
"""
build_nye26_spec.py — 生成 2027 元旦跨年音乐节 StrategySpec（阿岚 SOP 产出）

所有取值来源（不凭感觉）：
  · 画像包命中 → goal_intake.infer_audience_package 实测 score
  · 频次/静默窗/时段/levers/CTA/forbidden → references/audience-content-map.json
  · 波次数 → 服务端预算 D=78、C 未设置 → 基准 4 − 1 = 3
  · 落地页 slug →【国际化与落地页规则】第 2 条（按 cid 生成，不复用）
本脚本只负责生成与自检，最终 spec 由 validate_spec 交叉校验。
"""
import json

# ----------------------------------------------------------------- 并集工具
def union_pkg(codes=("HNW_FAMILY", "YOUNG_TREND")):
    d = json.load(open("references/audience-content-map.json", encoding="utf-8"))
    pk = {p["code"]: p for p in d["packages"]}
    picked = [pk[c] for c in codes]
    s = [p["strategy"] for p in picked]

    # 频次取最大值
    f24 = max(x["frequency"]["max_per_24h"] for x in s)
    f7 = max(x["frequency"]["max_per_7d"] for x in s)

    # 静默窗：两包一致则原样；不一致则取更宽（交集）并记录
    qh = s[0]["quiet_hours"]
    assert all(x["quiet_hours"] == qh for x in s), "两包静默窗不一致，需人工裁定"

    # 触达时段取并集：最早开始 ~ 最晚结束
    def span(w):
        a, b = w.split("-")
        return a, b
    spans = [span(w) for x in s for w in x["send_window"]]
    win = f"{min(a for a, _ in spans)}-{max(b for _, b in spans)}"

    # levers / CTA / 禁词 全量并集（保序去重）
    def uniq(seqs):
        out = []
        for sq in seqs:
            for v in sq:
                if v not in out:
                    out.append(v)
        return out
    return dict(
        freq24=f24, freq7=f7, quiet_hours=qh, send_window=win,
        levers=uniq([x["levers"] for x in s]),
        ctas=uniq([x["cta_templates"] for x in s]),
        forbidden=uniq([x["forbidden_phrases"] for x in s]),
    )


U = union_pkg()
print("并集结果：", json.dumps(U, ensure_ascii=False, indent=1))

# ----------------------------------------------------------------- 常量
GOAL = "newyear_music_fest_2027"
TOPIC = "2027 元旦跨年音乐节 · 意向登记与现场体验官招募"

# 两包 forbidden 合并后出现内部矛盾：YOUNG_TREND 的 lever「限时体验 / 限量稀缺」
# 与 HNW_FAMILY 的 forbidden「限时」直接冲突。规则要求 levers 必须全覆盖、
# forbidden 必须遵守 → 策略上保留 lever，但文案一律用「限量 / 场次有限 / 席位」表达，
# 严禁出现「限时」二字。此冲突已进 operator_review_notes 请运营拍板。
LEVER_NOTE = (
    "levers 全量并集（深度价值/数据对比/长期主义 + UGC 引用/限量稀缺/限时体验）；"
    "但 HNW_FAMILY forbidden 含「限时」，与 YOUNG_TREND lever「限时体验」互斥 → "
    "文案层面以「限量 / 场次有限 / 席位」承接稀缺感，不写「限时」二字"
)

def ev_map(score, note):
    return f"references/audience-content-map.json 画像包参数表（infer_audience_package 实测 score={score}，阈值 0.6）"


# ----------------------------------------------------------------- campaigns
def mk(cid, name, brief, seg, tags, lp, dep, editable, rationale, evidence,
       delay=0, variant=None, deferred=False):
    c = {
        "cid": cid,
        "name": name,
        "content_brief": brief,
        "content_emphasis": U["levers"],
        "segment": {"mode": "propose", "ref": seg},
        "send_conditions": {
            "delay_hours": delay,
            "max_per_24h": U["freq24"],
            "max_per_7d": U["freq7"],
            "quiet_hours": U["quiet_hours"],
        },
        "tags_to_write": tags,
        "email_mode": "generate",
        "email_ref": "",
        "landing_page_url": lp,
        "depends_on": dep,
        "editable_until_start": editable,
        "daily_adjust_window_hours": 24,
        "deferred": deferred,
        "rationale": rationale,
        "evidence": evidence,
    }
    if variant is not None:
        c["content_variant"] = variant
    return c


P = U["forbidden"]
def scan(t):
    hit = [w for w in P if w in t]
    assert not hit, f"命中禁词 {hit}: {t}"
    return t


campaigns = [
    # ---------------- 英文主稿 c1（seed：完全无认知）
    mk("c1", "2027 New Year Music Festival · Lineup Reveal (EN)",
       scan("Cross-year music lovers who know nothing about the festival yet and have not been touched by any wave; they lack one single anchor fact: who is on stage and when it starts."),
       "SEG_NYE26_CN_EN_SEED", ["nye26_c1_sent", "nye26_engaged"],
       "http://localhost:8080/c1-en", None, True,
       "首波只做「阵容与时间」这一件事，用可核验的阵容名单 + 场次时间建立最基础的认知锚点；不带任何价格与稀缺话术，先量出 seed 池的真实开信基线，为 c2/c3 定权重。频次取两包最大值 2/封·24h、4 封·7d，静默窗 22:00-09:00 原样沿用，触达时段取并集 12:00-22:00。",
       ev_map("HNW_FAMILY 0.7059 / YOUNG_TREND 0.6875",
              "触达参数取两包并集：max_per_24h=max(1,2)=2、max_per_7d=max(2,4)=4、"
              "send_window=[19:00-21:00]∪[12:00-14:00,20:00-22:00]=12:00-22:00、"
              "quiet_hours 两包一致 22:00-09:00 原样沿用。" ) + "；本波无历史活动数据可参照，转化预期数据缺失（data_missing）。"),

    # ---------------- 英文主稿 c2（engaged：看过但未到强意向）
    mk("c2", "2027 New Year Music Festival · Setlist & Field Map (EN)",
       scan("People who opened c1 but neither clicked through nor registered; they saw the lineup but still lack the practical information needed to decide to go: setlist times, field layout, on-site arrangements."),
       "SEG_NYE26_CN_EN_ENGAGED", ["nye26_c2_sent", "nye26_deep_engaged"],
       "http://localhost:8080/c2-en", "c1", False,
       "承接 c1 的开信未点击人群。本波只补「到现场之后会发生什么」这一层实操信息（场次时间表 / 场地分区 / 现场安排），不重复阵容信息。用数据对比与 UGC 引用两条 lever 并置：一边给客观场次数据，一边给真实听众反馈，满足 HNW 的可核验要求与 YOUNG 的口碑背书要求。",
       ev_map("HNW_FAMILY 0.7059 / YOUNG_TREND 0.6875",
              "内容侧重取两包 levers 并集中与本阶段匹配的部分（数据对比 / 长期主义 + UGC 引用）。")
       + "；分群与 c1 互斥（c1 排除 nye26_engaged），依据画像包参数表的意图分层惯例。",
       delay=72),

    # ---------------- 英文主稿 c3（intent：强意向 / 待转化）
    mk("c3", "2027 New Year Music Festival · Experience Officer Signup (EN)",
       scan("High-intent people who clicked twice or registered an interest: they lack the last thing needed to commit — a specific, limited role that makes registering feel worth it rather than a passive newsletter subscription."),
       "SEG_NYE26_CN_EN_INTENT", ["nye26_c3_sent", "nye26_strong_intent"],
       "http://localhost:8080/c3-en", "c2", False,
       "末波做角色升级而非促销：把「观众」包装成「现场体验官」，用稀缺席位 + 长期价值（深度幕后内容、年度权益）承接 HNW 的长期主义与 YOUNG 的稀缺心理。C 未设置、无营收目标，因此不写价格、不写折扣，只做意向登记，与 Brief 的「仅意向登记 / 品牌曝光」定位一致。",
       ev_map("HNW_FAMILY 0.7059 / YOUNG_TREND 0.6875",
              "本波同时需要 HNW 的「长期主义 / 深度价值」与 YOUNG 的「限量稀缺」，故取并集 levers 全量；"
              "因 Brief is_revenue=false、overall_conv 未设置，不引入任何价格或折扣字段。")
       + "；活动周期 D=78 天，已用尽（结束日 2026-12-30），无余量追加波次。",
       delay=72),

    # ---------------- 中文翻译稿 c1_zh
    mk("c1_zh", "2027 元旦跨年音乐节 · 阵容揭晓（中文）",
       scan("对跨年音乐节毫无认知、且未被任何波次触达的音乐爱好者；他们目前只缺一条最基础的事实：谁上台、几点开始。"),
       "SEG_NYE26_CN_ZH_SEED", ["nye26_c1_sent", "nye26_engaged"],
       "http://localhost:8080/c1_zh-zh", "c1", False,
       "c1 的中文翻译稿。受众含中国大陆且 locale 同时勾选 zh_CN/en_US，按规则英文为主稿、中文为双语备选，排在英文三波之后。触达参数与 c1 完全一致，不单独调优。",
       "【国际化与落地页规则】第 1 条：audience_region 含中国大陆 + locale 双语 → 英文主稿 + 中文翻译稿。"
       "翻译稿内容与主稿一一对应，不引入新的卖点或新的折扣。",
       variant=2),

    # ---------------- 中文翻译稿 c2_zh
    mk("c2_zh", "2027 元旦跨年音乐节 · 歌单与场地地图（中文）",
       scan("打开了 c1 但既未点进来也未登记的人；他们看到了阵容，却仍缺少决定去不去所需的实操信息：场次时间、场地分区、现场安排。"),
       "SEG_NYE26_CN_ZH_ENGAGED", ["nye26_c2_sent", "nye26_deep_engaged"],
       "http://localhost:8080/c2_zh-zh", "c2", False,
       "c2 的中文翻译稿，内容与主稿一一对应。depends_on 指向 c2（英文主稿）而非 c1_zh，保证中英两条链路读到同一批数据。",
       "【国际化与落地页规则】第 1 条 + 第 2 条：中文翻译稿落地页用 /c2_zh-zh，不复用英文主稿的 /c2-en。",
       delay=72, variant=2),

    # ---------------- 中文翻译稿 c3_zh
    mk("c3_zh", "2027 元旦跨年音乐节 · 现场体验官登记（中文）",
       scan("已二次点击或已登记的高意向人群；他们只缺最后一步——一个具体且有限的角色，让登记这件事本身值得做，而不是被动订阅一份活动资讯。"),
       "SEG_NYE26_CN_ZH_INTENT", ["nye26_c3_sent", "nye26_strong_intent"],
       "http://localhost:8080/c3_zh-zh", "c3", False,
       "c3 的中文翻译稿。末波同样只做意向登记、不做价格与折扣，与 Brief 的 is_revenue=false 一致。",
       "【国际化与落地页规则】第 1 条 + 第 2 条：中文翻译稿落地页用 /c3_zh-zh。",
       delay=72, variant=2),
]

SPEC = {
    "goal_id": GOAL,
    "objective": f"围绕「{TOPIC}」，在 2026-10-14 至 2026-12-30 的 78 天窗口内，"
                 f"分 3 波把「不知道 → 看过 → 高意向」的人群推到完成意向登记；"
                 f"无营收目标，只做品牌曝光与意向池沉淀。",
    "business_topic": TOPIC,
    "kpi": {"metric": "conversion", "target": 0.0},
    "locale": ["zh_CN", "en_US"],
    "audience_package": "HNW_FAMILY",
    "audience_profile": {
        "gender": "男",
        "income": "L1",
        "education": "名校",
        "industry": "IT",
        "source": "CTL",
        "region": "中国大陆",
    },
    "campaigns": campaigns,
    "service_sequences": [],
    "needs_operator_review": True,
    "operator_review_notes": [
        "【资产复用无法判定】本实例 23 封邮件全部为 AC27_* / F1_* 系列（id 161-182），"
        "无任何跨年音乐节资产；两条落地页 alias 也是 afc-cl-2627 / f1-racing-2027，均为赛事页。"
        "故 6 个 campaign 全部 email_mode=generate。需拍板：A) 先补齐 6 封邮件资产再推送；"
        "B) 接受系统按 email_brief 自动生成占位邮件（会落地成占位桩，需人工补文案）。",
        "【kpi 目标不可评估】Brief 的 overall_conv 未设置，按规则 kpi.target 只能填 0.0。"
        "这意味着本轮无法做转化率可达性判断，也无法据此调整波次权重。"
        "需拍板：是否补充一个目标转化率（如意向登记率 ≥0.08）作为验收线。",
        "【触达时段并集偏宽】两包并集后 send_window=12:00-22:00，横跨 10 小时，"
        "对 HNW 的「理性克制、报告感」调性偏松（该包原始窗口仅 19:00-21:00）。"
        "选项：A) 保持 12:00-22:00（严格执行并集规则）；B) 收窄为 19:00-21:00（贴合高净值调性，牺牲触达量）。",
        "【levers 与 forbidden 内部矛盾】YOUNG_TREND 的 lever「限时体验」与 "
        "HNW_FAMILY 的 forbidden「限时」直接冲突。规则要求 levers 全覆盖且 forbidden 必须遵守，"
        "故策略保留 lever、文案层面以「限量 / 场次有限 / 席位」承接稀缺感。"
        "需拍板：是否接受这一规避方案，或直接放弃 YOUNG_TREND 的限时类 lever。",
        "【分群为 propose 且需新建】6 个 SEG_NYE26_* 分群在 Mautic 实例中均不存在，"
        "按 SPEC 只声明不自动建库。需拍板：由谁按本 spec 的条件建库并回填真实 id，"
        "否则推送时会退化为空条件分群。",
        "【活动名称未命名】Brief 的「营销/活动名称」为空，goal_id 由本策略代拟为 "
        f"{GOAL}，business_topic 依据 objective 中的「2027 年元旦跨年音乐节」提炼。"
        "需运营确认正式活动名，回填后我会同步改写 campaign name、subject 与落地页文案。",
    ],
    "meta": {
        "generated_by": "阿岚（增长操盘手）SOP",
        "wave_count_rule": "服务端已算：活动周期 D=78 天（2026-10-14 ~ 2026-12-30，含首尾）→ 基准 4；"
                           "C 未设置 → −1；夹取 [1,5] → 3 波。Brief 未显式指定波次数，故取 3。",
        "i18n_rule": "audience_region 含中国大陆 + locale 同时含 zh_CN/en_US → "
                     "英文主稿 c1/c2/c3 在前，中文翻译稿 c1_zh/c2_zh/c3_zh 在后，共 3 波 × 2 语言 = 6 个 campaign。",
        "audience_package_union": LEVER_NOTE,
        "segment_taxonomy": "按意图天然互斥：SEED（未触达）→ ENGAGED（已触达未深读）→ INTENT（强意向），"
                            "后两类以 nye26_c1_sent / nye26_engaged 排除前序人群，不共用同一 segment。",
    },
}

if __name__ == "__main__":
    json.dump(SPEC, open("strategies/newyear_music_fest_2027_strategy_spec.json", "w",
                         encoding="utf-8"), ensure_ascii=False, indent=2)
    print("campaigns:", len(SPEC["campaigns"]))
    for c in SPEC["campaigns"]:
        print(" ", c["cid"], "|", c["segment"]["ref"], "|", c["landing_page_url"],
              "| dep=", c["depends_on"], "| lp_set=", c["send_conditions"])