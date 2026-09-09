import os
import json
import urllib.parse
import urllib.request as u, urllib.error

# 单元验证外链构造器（不依赖活服务）
import cockpit as C  # noqa: E402

BASE = os.environ.get("COCKPIT_BASE", "http://127.0.0.1:8090")
HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE_SPEC = os.path.join(HERE, "strategies", "example_strategy.json")

class NoRedirect(u.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

op = u.build_opener(u.ProxyHandler({}), NoRedirect)

def get(path):
    return op.open(BASE + path, timeout=10).read().decode()

def post(path, data: str):
    req = u.Request(BASE + path, data=data.encode(), method="POST")
    try:
        r = op.open(req, timeout=10)
        return r.status, r.headers.get("Location"), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location"), e.read().decode()

def post_json(path, obj: dict):
    req = u.Request(BASE + path, data=json.dumps(obj, ensure_ascii=False).encode(),
                    method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        r = op.open(req, timeout=10)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def check(name, cond, extra=""):
    print(("✅" if cond else "❌"), name, extra)


# ---------- 单元：Mautic 外链构造器（mock 资产读取，不依赖活服务/Mautic） ----------
C.mautic_read_assets = lambda env: {
    "available": True,
    "emails": [{"id": 99, "name": "EM_X", "alias": "EM_X"}],
    "segments": [{"id": 7, "name": "SEG_Y", "alias": "SEG_Y"}],
    "pages": [{"id": 3, "name": "LP_Z", "alias": "LP_Z"}],
}
_idx = C._mautic_asset_index()
check("外链索引 email 解析", _idx["email"].get("EM_X") == 99, f"id={_idx['email'].get('EM_X')}")
check("外链索引 segment 解析", _idx["segment"].get("SEG_Y") == 7)
check("外链 战役 URL", "/s/campaigns/123" in C._mautic_ext_link("campaign", "123", _idx),
      C._mautic_ext_link("campaign", "123", _idx))
check("外链 邮件 URL", "/s/emails/99/view" in C._mautic_ext_link("email", "EM_X", _idx),
      C._mautic_ext_link("email", "EM_X", _idx))
check("外链 分群 URL", "/s/segments/7" in C._mautic_ext_link("segment", "SEG_Y", _idx))
check("外链 落页 URL", "/s/landingpages/3" in C._mautic_ext_link("landingpage", "LP_Z", _idx))
check("外链 未连接返回空", C._mautic_ext_link("email", "NOPE", _idx) == "")

# ---------- 单元：约束红线 → quiet_hours 确定性解析（防 LLM 把午夜写成 09:00） ----------
from strategy_spec import (parse_quiet_hours, normalize_campaign, strategies_from_spec)  # noqa: E402
check("parse_quiet_hours 跨午夜保留 00:00", parse_quiet_hours(["20:00~00:00免打扰"]) == "20:00-00:00")
check("parse_quiet_hours 默认示例", parse_quiet_hours(["22:00-09:00 免打扰"]) == "22:00-09:00")
check("parse_quiet_hours 自然语言次日", parse_quiet_hours(["晚 20 点后不推送，次日 10 点再发"]) == "20:00-10:00")
check("parse_quiet_hours 无约束→None", parse_quiet_hours(["每周≤3封"]) is None)
# 红线必须覆盖 LLM 手填的 quiet_hours
_nc = normalize_campaign({"cid": "c1", "send_conditions": {"quiet_hours": "20:00-09:00"}},
                         0, quiet_hours_override="20:00-00:00")
check("红线覆盖 LLM 手填 quiet_hours", _nc["send_conditions"]["quiet_hours"] == "20:00-00:00",
      _nc["send_conditions"]["quiet_hours"])
# strategies_from_spec 自动从 goal.meta.constraints 派生红线
class _G:
    meta = {"constraints": ["20:00~00:00免打扰"]}
_ss = strategies_from_spec({"campaigns": [{"cid": "c1", "send_conditions": {"quiet_hours": "20:00-09:00"}}]},
                           _G())
check("strategies_from_spec 自动派生红线", _ss[0]["send_conditions"]["quiet_hours"] == "20:00-00:00",
      _ss[0]["send_conditions"]["quiet_hours"])
check("外链 未找到返回空", C._mautic_ext_link("email", "MISSING", _idx) == "")
# 直接渲染 program 验证 wave→campaign 重命名（不依赖 Mautic 连通）
_p = C._load_program("ucl2028_svctest")
if _p:
    _html = C._program_body(_p, "")
    check("program 渲染 wave→campaign 重命名", "campaign_1" in _html and "wave_1" not in _html)
    # 端到端：已推送拿到 campaign_id → 卡片渲染战役外链（email/segment 因 Mautic 未连通显示无对应）
    import copy as _copy
    _demo = _copy.deepcopy(_p)
    _demo["campaigns"][0]["proposal"]["deploy_result"] = {"campaign_id": "555", "dry_run": False}
    _demo_html = C._program_body(_demo, "")
    check("已推送 campaign 渲染战役外链", "/s/campaigns/555" in _demo_html,
          "campaign_id=555 → /s/campaigns/555")
else:
    check("program 渲染 wave→campaign 重命名", False, "（output/program_ucl2028_svctest.json 缺失）")

def program_of(gid):
    return json.load(open(os.path.join(HERE, "output", f"program_{gid}.json"), encoding="utf-8"))

# ---------- 单元：StrategySpec 与 Brief 一致性校验（硬阻断，纯单元不依赖活服务） ----------
from spec_validation import validate_spec, format_conflicts  # noqa: E402

_FORM_OK = {"objective": "UCL2028 门票预售：向目标球迷分群推送官方票务邮件",
            "goal_name": "UCL2028 预售", "start_date": "2028-05-01", "end_date": "2028-07-09",
            "overall_conv": "0.15", "locale": ["zh_CN"],
            "constraints": "20:00~00:00免打扰\n每周≤3封",
            "audience_region": ["中国大陆"], "is_revenue": "0", "budget": "0"}
_SPEC_OK = {"locale": ["zh_CN"], "audience_package": "GENERIC",
            "window": {"start": "2028-05-01", "end": "2028-07-09"},
            "kpi": {"target": 0.15},
            "campaigns": [{"cid": "c1", "send_conditions": {"quiet_hours": "20:00-00:00",
                                                            "max_per_7d": 3}}]}
_ctx = C._brief_ctx_from_form(_FORM_OK, ["zh_CN"])
check("brief_ctx 带上约束原文", "20:00~00:00免打扰" in (_ctx["constraints"] or ""))
check("一致 spec → 0 冲突（可生成）", validate_spec(_SPEC_OK, _ctx, "GENERIC") == [])
_bad = dict(_SPEC_OK, locale=["en_US"])
_bad["campaigns"] = [{"cid": "c1", "send_conditions": {"quiet_hours": "20:00-09:00",
                                                       "max_per_7d": 5}}]
_cs = validate_spec(_bad, _ctx, "GENERIC")
check("冲突 spec → 报出 locale/quiet_hours/max_per_7d",
      {c.field for c in _cs} == {"locale", "quiet_hours", "max_per_7d"},
      f"got={[c.field for c in _cs]}")
_card = C._conflicts_card_html(_cs, title="策略规格与基础信息冲突，未生成 Program")
check("冲突卡片含标题与每条冲突",
      "未生成 Program" in _card and all(l.strip("· ") in _card for l in format_conflicts(_cs)))
# 阻断回显：必须保留运营已填内容（objective / 约束 / 多选）
_pf = C._prefill_from_form(dict(_FORM_OK, strategy_spec="{...}"))
_page = C._brief_form([], "", None, None, _pf, _cs)
check("阻断页保留已填 objective", "UCL2028 门票预售" in _page)
check("阻断页保留约束原文", "20:00~00:00免打扰" in _page)
check("阻断页勾选已选语言 zh_CN", "value='zh_CN' checked" in _page)
check("阻断页列出全部冲突行",
      all(l.strip("· ") in _page for l in format_conflicts(_cs)))
check("阻断页不渲染自动纠正按钮", "一键纠正" not in _page and "自动纠正" not in _page)
# 端到端（离线）：直接调 handler —— 冲突 spec 必须不生成 Program、不落盘
class _FH:
    path = "/brief"
    code, body, loc = None, "", None

    def _send(self, code, body, headers=None):
        self.code, self.body = code, body

    def send_response(self, c):
        self.code = c

    def send_header(self, k, v):
        if k == "Location":
            self.loc = v

    def end_headers(self):
        pass


_fh = _FH()
_bad_spec = json.dumps({
    "goal_id": "ucl2028_conflict", "objective": "UCL2028 门票预售",
    "locale": ["en_US"], "audience_package": "GENERIC",
    "campaigns": [{"cid": "c1", "segment": {"mode": "propose", "ref": "SEG_A"},
                   "send_conditions": {"max_per_24h": 1, "max_per_7d": 5,
                                       "quiet_hours": "20:00-09:00"}}],
}, ensure_ascii=False)
C.Handler._handle_brief(_fh, dict(_FORM_OK, strategy_spec=_bad_spec))
check("handler：冲突 spec → 不生成 Program（无 302 跳转）",
      _fh.code == 200 and not _fh.loc, f"code={_fh.code} loc={_fh.loc}")
check("handler：返回阻断卡片", "策略规格与基础信息冲突，未生成 Program" in _fh.body)
check("handler：未落盘 program_ucl2028_conflict",
      not os.path.exists(os.path.join(HERE, "output", "program_ucl2028_conflict.json")))
# goal dict → brief_ctx（L1 确认策略路径用）
_g = C.parse_brief({"objective": "UCL2028 门票预售：向目标球迷分群推送官方票务邮件",
                    "locale": "zh_CN", "start_date": "2028-05-01", "end_date": "2028-07-09",
                    "kpi": {"type": "conversion_rate", "target": 0.15},
                    "audience_profile": {"age": "18-24", "region": ["中国大陆"]}})
_g.meta = {"locales": ["zh_CN"], "constraints": ["20:00~00:00免打扰"],
           "audience_package": _g.audience_package, "audience_match": _g.audience_match}
_gctx = C._brief_ctx_from_goal(_g.to_dict())
check("goal→brief_ctx 取到红线约束", "20:00~00:00免打扰" in "；".join(_gctx["constraints"]))
_bad_qh = {"locale": ["zh_CN"],
           "campaigns": [{"cid": "c1", "send_conditions": {"quiet_hours": "20:00-09:00"}}]}
check("goal→brief_ctx 冲突可检出（quiet_hours 不符）",
      [c.field for c in validate_spec(_bad_qh, _gctx, _g.audience_package)] == ["quiet_hours"],
      f"pkg={_g.audience_package}")

# ---------- 单元：总策略卡（画像包 + 内容/视觉方向 + 来源徽章） ----------
_prov = {"send_conditions": {"max_per_24h": 1, "max_per_7d": 3, "quiet_hours": "22:00-09:00"},
         "send_window": ["19:00-21:00"],
         "strategy_provenance": {"max_per_7d": "package", "max_per_24h": "spec",
                                 "quiet_hours": "red_line", "send_window": "default"}}
_pline = C._provenance_line(_prov)
check("来源徽章 画像包", "画像包" in _pline)
check("来源徽章 红线", "红线" in _pline)
check("来源徽章 默认", "默认" in _pline)
check("触达时段带值", "19:00-21:00" in _pline)
_s0 = C.strategies_from_spec({"campaigns": [{"cid": "c1"}]})[0]
_s0.update(_prov)  # 带上 send_window / strategy_provenance（模拟画像包注入后的策略）
_pg = {"goal_id": "unit", "goal": _g.to_dict(), "n_campaigns": 1,
       "campaigns": [{"cid": "c1", "wave_id": "wave_1", "status": "unreviewed",
                      "strategy": _s0, "proposal": C.compile(_g, _s0), "result": None}],
       "changelog": []}
_tcard = C._total_strategy_card(_pg)
check("总策略卡含画像包 code", _g.audience_package in _tcard, f"pkg={_g.audience_package}")
check("总策略卡含七属性", all(x in _tcard for x in ("年龄段", "性别", "月收入档", "教育经历",
                                                "行业", "首选来源", "国家/地区")))
check("总策略卡含内容方向", "内容方向" in _tcard and "CTA 模板" in _tcard)
check("总策略卡含视觉方向与配色色块", "视觉方向" in _tcard and "background:#" in _tcard)
check("总策略卡含 score/命中证据", "score" in _tcard and "命中证据" in _tcard)
_prog_html = C._program_body(_pg, "")
check("Program 页渲染总策略卡", "总策略（画像包 + 策略规划 + 属性）" in _prog_html)
check("Program 页 campaign 卡带来源徽章", "取值来源：" in _prog_html)

# ② L1「确认下阶段策略」：冲突 → 不应用、不写 changelog（离线直调 handler）
C._save_program(_pg)
_fh2 = _FH()
_fh2.path = "/program/unit/confirm-strategy"
C.Handler._handle_confirm_strategy(_fh2, {
    "cid": "c1",
    "strategy_spec": json.dumps({"campaigns": [{"cid": "c1", "send_conditions": {
        "quiet_hours": "20:00-09:00"}}]}, ensure_ascii=False)})
_p2 = C._load_program("unit") or {}
check("L1 确认：冲突策略 → 返回阻断卡片", "未应用该策略" in (_fh2.body or ""),
      f"code={_fh2.code}")
check("L1 确认：冲突策略 → 不写 changelog", not _p2.get("changelog"),
      f"changelog={_p2.get('changelog')}")
check("L1 确认：冲突策略 → 原 campaign 状态未改",
      (_p2.get("campaigns") or [{}])[0].get("status") == "unreviewed")
os.remove(os.path.join(HERE, "output", "program_unit.json"))

# ---------- 单元：生成提示词要求回显 audience_package 与业务主题 ----------
_prmpt = C.build_strategy_prompt({"goal_name": "UCL2028", "objective": "门票预售",
                                  "locale": ["zh_CN"], "audience_package": "YOUNG_TREND",
                                  "start_date": "2028-05-01", "end_date": "2028-07-09"})
check("提示词要求输出 business_topic", "business_topic" in _prmpt)
check("提示词回显 audience_package", "audience_package（YOUNG_TREND" in _prmpt)
check("提示词指向项目内画像包参数表", "references/audience-content-map.json" in _prmpt)

# ---------- 首页 + brief 页 ----------
check("首页", "活动驾驶舱" in get("/"))
# ---------- KPI 看板 (issue 2026-09-07) ----------
home = get("/")
check("首页含总览 KPI 标题", "总览 KPI" in home)
check("首页含 6 张 KPI 卡", home.count("kpi-card") >= 6)
check("KPI 卡含 4 种状态色(brand/gov/warn/ok)",
      "kpi-card brand" in home and "kpi-card gov" in home
      and "kpi-card warn" in home and "kpi-card ok" in home)
check("KPI 含核心维度标签",
      "Program" in home and "Campaign" in home and "待审" in home
      and "执行中" in home and "已发" in home and "达标/未达标" in home)
# ---------- Brief 预填 (回链) ----------
bf_pre = get("/brief?goal_id=ucl2028")
check("Brief?goal_id= 改 Brief 模式", "改 Brief" in bf_pre and "预填原 Program" in bf_pre)
check("Brief 预填 objective", "value='UCL Invite'" in bf_pre and "name='objective'" in bf_pre)
check("Brief 预填 goal_name", "value='ucl2028'" in bf_pre and "name='goal_name'" in bf_pre)
check("Brief 无效 goal_id 不报错(回落普通新建模式)",
      "改 Brief" not in get("/brief?goal_id=nonexistent_xyz_999"))
# ---------- Program 详情页改 Brief 按钮 ----------
prog = get("/program/ucl2028")
check("Program 详情含 改 Brief 按钮",
      "改 Brief" in prog and "href='/brief?goal_id=ucl2028'" in prog)
check("Program 详情 改 Brief 按钮含 title 提示",
      "title=" in prog and "预填原 Brief 字段" in prog)
bf = get("/brief")
check("Brief 含运营目标字段", "营销目标" in bf)
check("Brief 目标字段默认空", "UEFA" not in bf and "name='objective'" in bf)
check("Brief 含目标名称字段", "name='goal_name'" in bf)
check("Brief 含总体转化率字段", "name='overall_conv'" in bf)
check("Brief 不再让运营填单campaign点击率(系统反推,只读控件已下架)",
      "name='click_rate_disp'" not in bf and "name='click_rate'" not in bf
      and "此处不可手填" in bf)
check("Brief 不外显画像包(画像包由系统按 7 字段打分推断,不是 form input)",
      "name='audience_package'" not in bf and "系统推断" in bf)
check("Brief 含 7 个画像字段(年龄/性别/收入/教育/行业/来源/区域)",
      all(f"name='audience_{k}'" in bf for k in
          ("age", "gender", "income", "education", "industry", "source", "region")))
check("Brief 含画像匹配实时显示区(系统推断结果)",
      "id='audience-match-result'" in bf and "_updateMatch" in bf)
check("Brief 含是否涉及营收(默认无营收)",
      "name='is_revenue'" in bf and "value='0' selected" in bf)
check("Brief 预算字段默认隐藏(仅 is_revenue=1 才显示)",
      "id='budget_wrap'" in bf and "display:none" in bf.replace(" ", "").lower())
check("Brief 字段命名『营销/活动 内部简称』",
      "营销/活动 内部简称" in bf)
check("Brief 提示画像由系统按打分公式匹配",
      "打分公式" in bf)
check("Brief 含「用 WorkBuddy 生成策略」按钮", "gen-strategy-btn" in bf)
check("Brief 展示策略生成说明(端点优先/降级)",
      ("已配置策略自动生成端点" in bf) or ("未配置自动生成端点" in bf))
check("Brief 含约束字段", "name='constraints'" in bf)
check("Brief 含 StrategySpec 字段", "name='strategy_spec'" in bf)
check("Brief StrategySpec 已译中文", "策略规格（Agent 产出，可选）" in bf)
check("Brief 语言为下拉(中文/英文)", "中文" in bf and "英文" in bf and "name='locale'" in bf)
check("Brief 预算字段仅在 is_revenue=1 时显示(budget 已并入营收开关)",
      "无营收活动" not in bf and "仅审计/审批用" in bf)
check("Brief 不再让运营填分群", "name='audience_segment'" not in bf)
check("Brief 不再让运营填 KPI/落页/波次数",
      "name='kpi_target'" not in bf and "name='landing_page_url'" not in bf
      and "name='n_campaigns'" not in bf)
check("Brief 含 Agent 自动决策面板", "Agent 自动决策" in bf)
check("未提交策略时提示默认递进", "Agent 尚未产出策略" in bf)
check("Brief 不暴露频次闸门编辑", "频次闸门 1/24h" in bf and "name='max_per_24h'" not in bf)
check("Brief 含取消/返回列表按钮(显式href=/)",
      "取消并返回列表" in bf and "href='/'" in bf and "←" in bf)
# ---------- 必填/非必填视觉区分 (issue 2026-09-07) ----------
check("Brief 不再含必填/非必填图例说明(已移除)",
      "必填项" not in bf and "缺一不可" not in bf)
check("Brief objective 标 .req 必填星号",
      ('class="req"' in bf or "class='req'" in bf) and "营销目标" in bf)
check("Brief objective 有 HTML5 required 属性",
      "name='objective'" in bf and "required" in bf)
check("Brief 非必填字段标 .opt 可选小标", "class=\"opt\"" in bf)
check("Brief 含 objective 质量说明(非占位词)",
      "占位" in bf and "业务描述" in bf)

# ---------- wave→campaign 实时校验（svctest 详情页） ----------
svc = get("/program/ucl2028_svctest")
check("svctest 详情 wave→campaign 重命名", "campaign_1" in svc and "wave_1" not in svc)
check("svctest 详情含返回按钮", "返回" in svc and "history.back()" in svc)

# ---------- /brief?spec= 预览 Agent 策略（只读摘要）----------
pv = get("/brief?spec=" + EXAMPLE_SPEC.replace(os.sep, "/"))
check("策略预览含摘要标题", "策略摘要（只读" in pv)
check("策略预览含 rationale/evidence", "理由：" in pv and "依据：" in pv)
check("策略预览 generate 邮件显示[待生成]", "[待生成]" in pv)

# ---------- infer_audience_package 单元测试（系统推断画像包） ----------
import goal_intake as GI
inf = GI.infer_audience_package
m1 = inf({"age": "35-44", "gender": "男", "income": "L4", "education": "MBA", "industry": "IT"})
check("infer HNW_FAMILY 命中(男/35-44/IT/L4/MBA)",
      m1["code"] == "HNW_FAMILY" and m1["fallback"] is False
      and m1["score"] >= 0.6
      and "age=35-44" in m1["evidence"] and "industry=IT" in m1["evidence"],
      f"got {m1}")
m2 = inf({"age": "25-34", "gender": "女", "income": "L3", "education": "普通本科", "industry": "教育"})
check("infer PARENT_FAM 命中(女/25-34/L3/教育/普通本科)",
      m2["code"] == "PARENT_FAM" and m2["fallback"] is False
      and m2["score"] >= 0.6,
      f"got {m2}")
m3 = inf({})  # 全空
check("infer 全空 profile → GENERIC 兜底",
      m3["code"] == "GENERIC" and m3["fallback"] is True,
      f"got {m3}")
m4 = inf({"age": "55+", "industry": "医疗"})  # 不命中任何具名包
check("infer 不命中 → GENERIC 兜底(分数低)",
      m4["code"] == "GENERIC" and m4["fallback"] is True
      and m4["score"] < 0.6,
      f"got {m4}")
m6 = inf({"age": "25-34", "gender": "女", "income": "L4", "education": "普通本科", "industry": "教育"})
# 命中包时 alternatives 字段始终是 list（设计上是互斥包，所以常为空，但字段必须存在供前端用）
check("infer 命中时 alternatives 字段为 list(供前端/详情页展示候选)",
      m6["code"] == "PARENT_FAM" and isinstance(m6.get("alternatives"), list),
      f"got {m6}")

# ---------- _check_objective_quality 单元测试 (issue 2026-09-07, 防「测试」输入派生 8 campaign) ----------
q = GI._check_objective_quality
check("quality 空字符串 → 拒绝", q("") is not None and "为空" in q(""))
check("quality 纯空白 → 拒绝", q("   ") is not None)
check("quality 短字符串(3字符) → 拒绝", q("abc") is not None and "过短" in q("abc"))
check("quality 占位词 测试 → 拒绝", q("测试") is not None and ("过短" in q("测试") or "占位" in q("测试")))
check("quality 占位词 test → 拒绝", q("test") is not None and "占位" in q("test"))
check("quality 占位词 demo → 拒绝", q("demo") is not None and "占位" in q("demo"))
check("quality 占位词 1234 → 拒绝(纯数字)", q("1234") is not None)
check("quality 有效目标 → 通过", q("邀请 2028 欧超决赛意向客户") is None)
check("quality 有效英文目标 → 通过", q("Increase brand awareness for Q4") is None)

# ---------- 服务端薄输入拒绝 (issue 2026-09-07 修复验证) ----------
st, loc, body = post("/brief", "objective=" + urllib.parse.quote("测试") + "&start_date=2028-05-01&end_date=2028-07-09&goal_name=demo&is_revenue=0")
check("服务端 objective=测试 → 200 错误页(非 302)",
      st == 200 and "营销目标" in body and ("过短" in body or "占位" in body or "命中占位" in body),
      f"st={st} loc={loc}")
st, loc, body = post("/brief", "objective=test&start_date=2028-05-01&end_date=2028-07-09&goal_name=demo&is_revenue=0")
check("服务端 objective=test → 200 错误页(占位模式)",
      st == 200 and "命中占位" in body, f"st={st} loc={loc}")
st, loc, body = post("/brief", "objective=ab&start_date=2028-05-01&end_date=2028-07-09&goal_name=xx&is_revenue=0")
check("服务端 objective=ab → 200 错误页(过短)",
      st == 200 and "过短" in body, f"st={st} loc={loc}")
st, loc, body = post("/brief", "objective=正式营销目标&start_date=2028-05-01&end_date=2028-07-09&goal_name=ok&is_revenue=0")
check("服务端 objective=正式营销目标 → 302 成功",
      st == 302, f"st={st} loc={loc}")


# ---------- 路径 A：未提交 StrategySpec → 默认递进策略（按日期跨度派生 N）----------
st, loc, _ = post("/brief",
    "objective=TEST+GOAL&locale=zh_CN&is_revenue=0&budget=0&"
    "audience_age=35-44&audience_gender=%E7%94%B7&audience_income=L4&"
    "audience_education=MBA&audience_industry=IT&audience_source=&audience_region=%E4%B8%AD%E5%9B%BD%E5%A4%A7%E9%99%86&"
    "start_date=2028-05-01&end_date=2028-07-09&"
    "constraints=22%3A00-09%3A00+%E5%85%8D%E6%89%93%E6%89%B0")
check("Brief→302 Program", st == 302, f"loc={loc}")
gid = loc.split("/")[-1]

ph = get(f"/program/{gid}")
check("Program 含 3 campaign", ("campaign_1" in ph) and ("campaign_3" in ph))
check("Program 含治理节点", "sourcemarketing.frequency_gate" in ph)
check("Program 事件图渲染为流程图", "<svg" in ph)
check("Program 含 Mautic 资产清单", "Mautic 资产清单" in ph)
check("Program 含每campaign目标编辑", "name='conv_target'" in ph)
check("Program 头部展示目标名称", "目标名称" in ph)
check("Program 展示运营约束", "免打扰" in ph)
check("Program 标记默认策略来源", "默认递进策略" in ph)
check("Program 首波初始为未审核", "未审核" in ph)
check("Program 含派生计划摘要(系统反推点击率)", "派生计划摘要" in ph)
check("Program 告知合理性判定", "合理性判定" in ph)
check("Program 含 Agent 优化说明", "Agent 优化说明" in ph)
check("Program 反推点击率字段已落库", "click_rate" in program_of(gid)["plan"])
# 画像包服务端推断：Path A 提交的是男/35-44/IT/L4/MBA 字段组合，应自动命中 HNW_FAMILY
prog = program_of(gid)
check("Program 画像包由服务端推断(非表单传)",
      prog["goal"]["audience_package"] == "HNW_FAMILY"
      and prog["goal"]["audience_match"].get("fallback") is False
      and prog["goal"]["audience_match"]["score"] >= 0.6
      and "age=35-44" in prog["goal"]["audience_match"]["evidence"],
      f"got package={prog['goal']['audience_package']} match={prog['goal']['audience_match']}")

c1 = f"{gid}_c1"
st, _, body = post(f"/program/{gid}/campaign/{c1}/approve", "approver=alice")
check("campaign 审批 APPROVED", "APPROVED" in body)

pp = f"output/program_{gid}.json"
prog = json.load(open(pp, encoding="utf-8"))
c = next(x for x in prog["campaigns"] if x["cid"] == c1)
c["proposal"]["graph"][0]["type"] = "TAMPERED"
json.dump(prog, open(pp, "w", encoding="utf-8"))
st, _, body = post(f"/program/{gid}/campaign/{c1}/approve", "approver=bob")
check("篡改后审批 REJECTED", "REJECTED" in body)
c["proposal"]["graph"][0]["type"] = "decision.segment"
json.dump(prog, open(pp, "w", encoding="utf-8"))

st, _, body = post(f"/program/{gid}/complete", f"cid={c1}&conversion=0.05&unsub=0.001")
check("完成回写触发自适应", "下游改写" in body)
check("完成首波→状态 done_met/done_below",
      json.load(open(pp, encoding="utf-8"))["campaigns"][0]["status"] in ("done_met", "done_below"))
prog = json.load(open(pp, encoding="utf-8"))
c2 = next(x for x in prog["campaigns"] if x["cid"] == f"{gid}_c2")
sc = c2["strategy"]["send_conditions"]
check("下游提频(乏力: +2)", sc["max_per_24h"] >= 3, f"max_per_24h={sc['max_per_24h']}")
check("下游换内容变体", c2["strategy"]["content_variant"] >= 1)
check("下游加 broaden/reengage tag", ("broaden" in c2["strategy"]["tags_to_write"]))
check("下游重算 plan_hash", c2["proposal"]["plan_hash"])

c2id = f"{gid}_c2"
st, _, body = post(f"/program/{gid}/complete", f"cid={c2id}&conversion=0.30&unsub=0.001")
prog = json.load(open(pp, encoding="utf-8"))
c3 = next(x for x in prog["campaigns"] if x["cid"] == f"{gid}_c3")
check("达标下游降本(降频)", c3["strategy"]["send_conditions"]["max_per_24h"] <= 2,
      f"max_per_24h={c3['strategy']['send_conditions']['max_per_24h']}")

# ---------- 路径 B：提交 Agent StrategySpec → N 由 campaigns 决定 ----------
st, loc, body = post("/brief", "objective=UCL+2028&strategy_spec=" + EXAMPLE_SPEC.replace(os.sep, "/"))
check("StrategySpec Brief→302 Program", st == 302, f"loc={loc} {body[:120]}")
gid2 = loc.split("/")[-1]
prog2 = program_of(gid2)
check("策略路径生成 2 个 campaign", prog2["n_campaigns"] == 2,
      f"n={prog2['n_campaigns']}")
cids = [c["cid"] for c in prog2["campaigns"]]
check("cid 取自 StrategySpec", cids == ["ucl2028_c1", "ucl2028_c2"], f"{cids}")
segs = [c["strategy"]["segment"] for c in prog2["campaigns"]]
check("两个 campaign 分群不同", len(set(segs)) == 2, f"{segs}")
modes = [c["strategy"]["email_mode"] for c in prog2["campaigns"]]
check("一个 reuse 一个 generate", modes == ["reuse", "generate"], f"{modes}")
check("reuse 用真实资产 ID",
      prog2["campaigns"][0]["strategy"]["email_ref"] == "EM_UCL2028_TICKET_V1")
hashes = [c["proposal"]["plan_hash"] for c in prog2["campaigns"]]
check("两份 proposal plan_hash 不同", hashes[0] != hashes[1],
      f"{hashes[0][:12]}… vs {hashes[1][:12]}…")
pg2 = get(f"/program/{gid2}")
check("Program 页展示策略理由/依据", "理由：" in pg2 and "依据：" in pg2)
check("Program 页展示[待生成]邮件", "[待生成]" in pg2)
check("Program 页展示变体 headline", "你的优先购票通道已开启" in pg2)
check("Program 标记 Agent 策略来源", "Agent 策略" in pg2)

# ---------- 路径 C：service 序列 + deferred 波次 + KPI 未设置 ----------
# （贴 JSON 文本提交，验证 service 与 promo 解耦、deferred 不自动发、R 未给不算达成率）
SPEC_C = {
    "goal_id": "ucl2028_svctest",
    "objective": "UCL 2028 意向登记（service 解耦 + deferred 验证）",
    "kpi": {"metric": "conversion", "target": 0.0},
    "locale": ["zh_CN"],
    "campaigns": [
        {"cid": "svctest_c1", "name": "种子波",
         "segment": {"mode": "propose", "ref": "SEG_SEED"},
         "send_conditions": {"delay_hours": 0, "max_per_24h": 1, "max_per_7d": 1,
                             "quiet_hours": "22:00-09:00"},
         "tags_to_write": ["svctest_invited"]},
        {"cid": "svctest_c2", "name": "host 确认波（deferred）", "deferred": True,
         "segment": {"mode": "propose", "ref": "SEG_HOST_POOL"},
         "send_conditions": {"delay_hours": 264, "max_per_24h": 1, "max_per_7d": 2},
         "tags_to_write": ["svctest_host"]},
    ],
    "service_sequences": [
        {"sid": "svc_svctest_confirm", "name": "登记确认件", "intent": "service",
         "class": "service", "counts_toward_promo_cap": False,
         "exempt_from_promo_suppression": True, "quiet_hours_exempt": True,
         "send_within_minutes": 5,
         "trigger": {"mode": "event", "event": "表单提交成功", "delay_hours": 0},
         "tags_to_write": ["svctest_registered"]},
    ],
}
st, loc, body = post("/brief", "objective=svctest&strategy_spec="
                     + urllib.parse.quote(json.dumps(SPEC_C, ensure_ascii=False)))
check("service/deferred Brief→302", st == 302, f"loc={loc} {body[:150]}")
gid3 = loc.split("/")[-1]
prog3 = program_of(gid3)
check("promo 仍为 2 波（service 不混入）", prog3["n_campaigns"] == 2)
check("service 序列单独挂载", prog3.get("n_service_sequences") == 1)
sts = {c["cid"]: c["status"] for c in prog3["campaigns"]}
check("c5/c2 置为 deferred", sts.get("svctest_c2") == "deferred", f"{sts}")
check("非 deferred 波初始为未审核", sts.get("svctest_c1") == "unreviewed")
svc3 = prog3["service_sequences"][0]
gtypes3 = [n["type"] for n in svc3["proposal"]["graph"]]
check("service 不注入 promo 频次闸门", not any("frequency_gate" in t for t in gtypes3), f"{gtypes3}")
check("service 不注入锚点仲裁", not any("anchor" in t for t in gtypes3))
gr3 = next(n for n in svc3["proposal"]["graph"] if n["id"] == "n_guardrail")
check("service 护栏豁免 suppress_promo/comm_freeze",
      "suppress_promo" in gr3["params"].get("exempt_from", [])
      and "comm_freeze" in gr3["params"].get("exempt_from", []))
check("service 事件触发（不看 segment）",
      svc3["proposal"]["graph"][0]["type"] == "decision.event_trigger"
      and svc3["strategy"]["segment"] == "")
check("tag 经 tag-rule 通路写入",
      next(n for n in svc3["proposal"]["graph"] if n["id"] == "n_tag")["params"]["via"] == "tag_rule")
check("service 状态为 armed（不进 promo 排期）", svc3["status"] == "armed")
# deferred 波：推送须被拒；启用后转 pending
st, _, body = post(f"/program/{gid3}/campaign/svctest_c2/activate", "")
check("deferred 波可启用", "已启用" in body, f"st={st}")
prog3 = program_of(gid3)
check("启用后转未审核（回到标准通道）",
      next(c for c in prog3["campaigns"] if c["cid"] == "svctest_c2")["status"] == "unreviewed")
# KPI target=0 → 目标未设置，不做达成率改写
st, _, body = post(f"/program/{gid3}/complete", "cid=svctest_c1&conversion=0.02&unsub=0.001")
check("KPI 未设置时不做达成率改写", "未设置" in body, f"{body[:120]}")
prog3 = program_of(gid3)
c2b = next(c for c in prog3["campaigns"] if c["cid"] == "svctest_c2")
check("KPI 未设置：不提频不加 urgency/broaden",
      c2b["strategy"]["send_conditions"]["max_per_24h"] == 1
      and not ({"urgency", "broaden", "reengage"} & set(c2b["strategy"]["tags_to_write"])))
pg3 = get(f"/program/{gid3}")
check("Program 页渲染服务序列区块", "服务序列（service/transactional）" in pg3)
check("Program 页提示 KPI 未设置", "KPI 目标值未设置" in pg3)

# ---------- 路径 D：多文件合并（send_strategy + content_map）----------
SEND = os.path.join(HERE, "strategies", "ucl2028_send_strategy.json").replace(os.sep, "/")
CONTENT = os.path.join(HERE, "strategies", "ucl2028_content_map.json").replace(os.sep, "/")
BOTH = SEND + "," + CONTENT
pv2 = get("/brief?spec=" + BOTH)
check("多文件预览显示合并徽章", "已合并 2 个策略文件" in pv2)
st, loc, body = post("/brief", "objective=UCL+Invite&strategy_spec=" + urllib.parse.quote(BOTH))
check("多文件 Brief→302", st == 302, f"loc={loc}")
gid4 = loc.split("/")[-1]
prog4 = program_of(gid4)
cs4 = prog4["campaigns"]
segs4 = [c["strategy"]["segment"] for c in cs4]
check("合并后 campaigns=5", len(cs4) == 5, f"n={len(cs4)}")
check("DISTINCT segment=5", len(set(segs4)) == 5, f"{sorted(set(segs4))}")
check("c1 复用真实资产 EM_UCL2028_INVITE",
      cs4[0]["strategy"]["email_ref"] == "EM_UCL2028_INVITE", cs4[0]["strategy"]["email_ref"])
modes4 = {c["cid"]: c["strategy"]["email_mode"] for c in cs4}
check("c3/c4/c5 为 generate",
      modes4.get("ucl2028_c3") == "generate" and modes4.get("ucl2028_c4") == "generate"
      and modes4.get("ucl2028_c5") == "generate", f"{modes4}")
lp4 = sorted({c["strategy"]["landing_page_url"] for c in cs4})
check("落页 URL 来自 content_map",
      lp4 == ["http://localhost:8080/s/ucl2028-bridge"], f"{lp4}")
c5_4 = next(c for c in cs4 if c["cid"] == "ucl2028_c5")
check("c5 状态 deferred", c5_4["status"] == "deferred")
check("c5 带启用条件说明", bool(c5_4["strategy"].get("deferred_enable_condition")))
check("service 恰好 1 条", prog4.get("n_service_sequences") == 1)
s4 = prog4["service_sequences"][0]
check("service 正文来自 content_map", "已收到你的 2028 欧冠决赛" in s4["strategy"]["subject"])
check("service 声明静默窗豁免 ≤5min",
      s4["strategy"]["send_conditions"]["quiet_hours_exempt"] is True
      and s4["strategy"]["send_conditions"]["send_within_minutes"] == 5)
gr4 = next(n for n in s4["proposal"]["graph"] if n["id"] == "n_guardrail")
check("豁免写入事件图（可审计）", gr4["params"].get("quiet_hours_exempt") is True)
# 审批门：未确认豁免 → 驳回；确认后 → 通过
st, _, body = post(f"/program/{gid4}/service/{s4['sid']}/approve", "approver=alice")
check("未确认静默窗豁免 → REJECTED", "REJECTED" in body)
st, _, body = post(f"/program/{gid4}/service/{s4['sid']}/approve",
                   "approver=alice&ack_quiet_exempt=on")
check("确认豁免后 → APPROVED", "APPROVED" in body)
pg4 = get(f"/program/{gid4}")
check("Program 页明示静默窗豁免", "已豁免静默窗" in pg4)

print("DONE gid=", gid, " gid2=", gid2, " gid3=", gid3, " gid4=", gid4)

# ---------- 路径 E：提交总体目标转化率 → 系统反推单campaign点击率 + 合理性 ----------
st, loc, _ = post("/brief",
    "objective=CONV+GOAL&locale=zh_CN&is_revenue=0&budget=0&"
    "start_date=2028-05-01&end_date=2028-07-09&"
    "overall_conv=0.15")
check("Conv Brief→302 Program", st == 302, f"loc={loc}")
gid5 = loc.split("/")[-1]
ph5 = get(f"/program/{gid5}")
prog5 = program_of(gid5)
check("Conv 派生 click_rate>0", prog5["plan"]["click_rate"] > 0, f"cr={prog5['plan']['click_rate']}")
check("Conv 合理(reasonable=True)", prog5["plan"]["reasonable"] is True, f"n={prog5['plan']['n_campaigns']}")
check("Conv campaign 数受日期跨度约束(1<=n<=8)",
      1 <= prog5["plan"]["n_campaigns"] <= 8, f"n={prog5['plan']['n_campaigns']}")
check("Conv per_campaign_target=oc/n",
      abs(prog5["plan"]["per_campaign_target"] - round(0.15 / prog5["plan"]["n_campaigns"], 4)) < 1e-9,
      f"t={prog5['plan']['per_campaign_target']}")
check("Conv Program 展示反推点击率+合理性", "推算" in ph5 and "合理性判定" in ph5)
check("Conv Program 展示 Agent 优化说明", "Agent 优化说明" in ph5)

# ---------- 路径 F：高目标 + 短跨度 → 点击率超阈值，标记「需优化」 ----------
st, loc, _ = post("/brief",
    "objective=HIGH+GOAL&locale=zh_CN&is_revenue=0&budget=0&"
    "start_date=2028-06-01&end_date=2028-06-30&"
    "overall_conv=0.50")
check("HighConv Brief→302 Program", st == 302, f"loc={loc}")
gid6 = loc.split("/")[-1]
prog6 = program_of(gid6)
check("HighConv 标记需优化(reasonable=False)",
      prog6["plan"]["reasonable"] is False, f"cr={prog6['plan']['click_rate']} n={prog6['plan']['n_campaigns']}")
check("HighConv 优化说明指向超阈值压缩节奏", "超阈值" in prog6["plan"]["optimization_note"])

# ---------- 路径 G：策略生成按钮后端（无端点 → 降级复制提示词） ----------
st_g, body_g = post_json("/brief/generate-strategy",
    {"goal_name": "SMOKE", "objective": "2028 欧冠决赛邀请", "start_date": "2028-05-01",
     "end_date": "2028-07-09", "overall_conv": "0.15", "budget": "0", "locale": "zh_CN",
     "constraints": "22:00-09:00 免打扰"})
gj = json.loads(body_g)
check("策略生成端点返回 JSON", st_g == 200 and isinstance(gj, dict), f"st={st_g}")
check("无端点时降级 fallback=True", gj.get("fallback") is True, f"{gj.get('error','')}")
check("降级返回自包含提示词", "StrategySpec" in gj.get("prompt", ""))
check("提示词含 Brief 目标", "2028 欧冠决赛邀请" in gj.get("prompt", ""))

# ---------- 路径 H：PoC graph → Mautic 7 events + canvasSettings 转换器（Option A） ----------
import plan_compiler as pc
from goal_intake import parse_brief

def _compile_mautic(objective, intent, **kw):
    spec = parse_brief({"objective": objective, "audience_segment": "SEG_X",
                        "landing_page_url": "http://localhost:8080/s/lp", "locale": "zh"})
    strat = {"cid": "T_" + intent, "wave_id": "wave_1", "variant_id": "v0", "intent": intent,
             "email_ref": 1, "segment_id": 7, "send_conditions": {"delay_hours": 24},
             "tags_to_write": ["TAG_A"], **kw}
    return pc.compile(spec, strat)

# PROMO 路径
promo = _compile_mautic("promo conv", "promo")
pev = promo["mautic_events"]
pcs = promo["mautic_canvas"]
pids = {n["id"] for n in pcs["nodes"]}
check("Mautic events 非空", len(pev) > 0, f"n={len(pev)}")
check("canvasSettings.nodes 与 events 数量一致", len(pcs["nodes"]) == len(pev))
check("每个 event 用 newN 临时 id", all(e["id"].startswith("new") for e in pev))
check("event type 均为 Mautic 注册类型",
      all(e["type"] in {"email.send", "email.click", "lead.changetags", "lead.dnc",
                        "lead.field_value"} for e in pev))
check("promo 含 email.send（主+兜底≥2）", sum(1 for e in pev if e["type"] == "email.send") >= 2)
check("promo 含 email.click 决策", any(e["type"] == "email.click" for e in pev))
check("promo 含 lead.changetags 打标签", any(e["type"] == "lead.changetags" for e in pev))
check("promo 决策 yes/no 锚点都存在",
      any(c["anchors"]["source"] == "yes" for c in pcs["connections"])
      and any(c["anchors"]["source"] == "no" for c in pcs["connections"]))
check("wait 计时并入 email.click（trigger=interval）",
      any(e["type"] == "email.click" and e.get("triggerMode") == "interval" for e in pev))
check("连线端点均为真实节点（lists 为 source 例外）",
      all((c["sourceId"] == "lists" or c["sourceId"] in pids) and c["targetId"] in pids
          for c in pcs["connections"]))
check("汇聚节点（tag+log）按 yes/no 分支复制",
      sum(1 for e in pev if e["type"] == "lead.changetags") >= 2)
check("提供 lists 作为 lead source", promo.get("mautic_lists") == [{"id": 7}])
check("api_calls 第一步写入 events+canvasSettings（不再 importEventGraph）",
      "events" in promo["api_calls"][0]["body"]
      and "canvasSettings" in promo["api_calls"][0]["body"]
      and "importEventGraph" not in str(promo["api_calls"]))

# SERVICE 路径（单路径，无分支）
svc = _compile_mautic("svc conv", "service", trigger={"mode": "event", "event": "form.submit"})
sev = svc["mautic_events"]
scs = svc["mautic_canvas"]
check("service 链为线性（无 yes/no 锚点）",
      not any(c["anchors"]["source"] in ("yes", "no") for c in scs["connections"]))
check("service 含 email.send", any(e["type"] == "email.send" for e in sev))
check("service 不含 email.click 决策", not any(e["type"] == "email.click" for e in sev))

print("DONE2 gid5=", gid5, " gid6=", gid6)
