# WaterBomb 2026 海外推广 · 营销规划（草稿 v1，待拍板）

> 生成时间：2026-09-10 ｜ 数据源：waterbombfestival.com 官网 + 公开巡演日程检索
> 状态：**未执行**。需先确认第 0 节的 3 个问题，再落地 spec / 落地页 / Mautic 推送。

---

## 0. 三个必须先拍板的问题

### 0.1 时间窗与真实赛程错位（最重要，会推翻现有 5 波方案）

你给的活动窗口是 **2026-09-01 → 2026-10-30**。WaterBomb 2026 全球巡演实际日程：

| 站点 | 日期 | 场地 | 备注 |
|---|---|---|---|
| Seoul | 7/24–7/26 | KINTEX Outdoor Global Stage, Goyang | 已结束 |
| Busan | 8/8 | Lotte World Adventure Busan | 已结束 |
| Sokcho | 8/22 | Hanwha Resort Seorak Sorano | 已结束 |
| Kaohsiung | 9/12–9/13 | 高雄夢時代對面廣場 | **中文市场，与"不要中文"冲突，排除** |
| **Las Vegas（美国）** | **9/19–9/20** | **Craig Ranch Regional Park, North Las Vegas, NV** | ✅ 窗口内唯一合规锚点 |
| Macau | 11/8–11/9 | Macau Outdoor Performance Venue | **超出窗口** |
| Ho Chi Minh City | 11/15–11/16 | Van Phuc City | **超出窗口** |

**结论**：

- 窗口内唯一符合「海外 + 英文 + 无中文」的锚点是 **Las Vegas 9/19–9/20**。今天 9/10，**距开演只剩 9 天**。
- 9/20 之后到 10/30 整整 **40 天没有可卖的赛事**（下一站澳门在 11/8）。
- 现有 `waterbomb_2026_strategy_spec.json` 把 5 波平铺在 9/1、9/13、9/25、10/7、10/19 —— **其中 4 波落在赛事之后，属于无效投放**。

**三个选项，我推荐 A：**

| 选项 | 做法 | 代价 |
|---|---|---|
| **A（推荐）** | 保持 9/1–10/30 窗口，但**重排为「3 波 LV 冲刺 + 2 波转澳门候补」**，让 10 月那两波有真实卖点 | 需要接受"10 月卖的是澳门 11/8，不是 LV" |
| B | 把窗口延到 **11/16**，覆盖澳门 11/8–9 + 胡志明 11/15–16 | 活动周期从 60 天拉到 67 天，且要改 brief |
| C | 维持原窗口原节奏 | 4/5 的投放打空，不建议 |

> ⚠️ 另一个口径问题：部分票务/资讯站把 9/19–9/20 这站标为 **「WaterBomb LA 2026」**，但场地在 **North Las Vegas**；另有媒体直称 **Waterbomb Las Vegas**。
> 对外文案前必须跟主办方口径确认，否则落地页地名写错会直接伤害可信度。**年龄门槛同样未公布**（韩国站 19+、高雄站 18+，LV 站未见官方数字）。

### 0.2 受众画像为什么是 GENERIC —— 已修，但还有残留

**根因（已修）**：打分器把「未填字段」当成 0 分。YOUNG_TREND 定义了 5 个字段，你只填了 age + source，其余一旦 miss 就是 0 → 总分被压到阈值 0.6 以下 → 兜底 GENERIC。

按你的口径改成「**留空 = 不限受众 = 全选 = 满分**」后，实测：

| 输入 | 结果 |
|---|---|
| `source=CSTS` + `age=18-24` | **YOUNG_TREND 1.00（显式证据 0.30）** ✅ |
| `source=CSTS` + `age=[18-24, 25-34]` | **YOUNG_TREND 1.00（证据 0.30）** ✅ |
| 只填 `age` | YOUNG_TREND 1.00（证据 0.20，刚好过线） |
| 只填 `source=CSTS` | 分数 1.00 但证据 0.10 < 0.20 → 仍 GENERIC（设计如此：单一弱字段不足以下判断） |
| 全空 | GENERIC |

**残留问题 A：英文枚举值匹配不上中文画像表。**
画像包 match 表是中文枚举，但 en_US brief 抽出来的是英文值 → 静默 miss：

```
YOUNG_TREND gender 枚举: ['男','女']        -> 'male'  命中? False
YOUNG_TREND education 枚举: ['普通本科','其他'] -> 'elite' 命中? False
```

同一份画像，中文值打分 **1.00**，英文值只有 **0.6875**。当前 case 侥幸仍过线，但这是定时炸弹。

**残留问题 B：没有「兴趣」维度。**
现有 7 个字段全是人口统计（年龄/性别/收入/学历/行业/来源/地域），**装不下"音乐爱好者"**。你的核心诉求之一目前完全没进打分。

### 0.3 10% 表单提交率：可行，但有前提

- **口径**：建议定义为「唯一访客提交率（UV-based），去重 + 排除 bot」。用 PV 口径会虚高。
- **基准**：邮件引流到独立 LP，冷量提交率通常 **2–5%**；10% 属于高位目标。
- **能不能到**：CSTS 存量渠道属相对 warm 的流量，**8–12% 可期**；若掺冷量则回落到 3–5%。
- 具体杠杆见第 3 节。

---

## 1. 受众映射（修正后）

| 你的描述 | 落到字段 | 值 |
|---|---|---|
| CSTS 渠道 | `source` | `CSTS` |
| 年龄 <30 岁 | `age` | `18-24` + `25-34`（多选，跨两个 band） |
| 海外用户 | `region` | 海外 / overseas（无画像包定义该字段，仅作过滤用） |
| 音乐爱好者 | `interest` | ⚠️ **当前无此字段**，见 0.2 残留问题 B |
| 目标画像包 | — | **YOUNG_TREND（年轻潮流客）** |

打分结果：`YOUNG_TREND 1.00 / 显式证据 0.30`，`GENERIC` 兜底不再出现。

---

## 2. 波次编排（方案 A：3 波冲刺 + 2 波转澳门）

文案支柱取自官网三大关键词：**ESCAPE / ENERGY / EXPERIENCE**。

### Phase 1 — Las Vegas 冲刺（9/11 → 9/18）

| cid | 发送日 | 主题 | 角度 | CTA |
|---|---|---|---|---|
| c1 | 9/11 (五) | WaterBomb lands in Las Vegas — Sep 19–20 | ESCAPE | Register your interest |
| c2 | 9/14 (一) | The lineup + **Pick your team** | ENERGY | Choose your team & register |
| c3 | 9/17 (四) | Last call: gates, what to bring, age gate | EXPERIENCE | Register now |

### Phase 2 — 赛事周末（9/19–9/20）

**冻结全部促销发送**，只跑事务性确认（`svc1`）。符合治理原则「事务性触达永不冻结」的反面——即促销此时必须让位。

### Phase 3 — 转澳门候补（9/23 → 10/30）

| cid | 发送日 | 主题 | 角度 | CTA |
|---|---|---|---|---|
| c4 | 9/23 (三) | Recap + **Macau 11/8–9 waitlist opens** | 回顾 + 下一站 | Join the Macau waitlist |
| c5 | 10/15 (四) | Macau waitlist: your spot + 早鸟预告 | 价值确认 | Confirm your spot |

### 服务序列（事务性，不占促销频控）

| sid | 触发 | 主题 |
|---|---|---|
| svc1 | `form.submit`（0 延迟） | You're registered for WaterBomb 2026 + 加入日历 |

---

## 3. 落地页 + 报名表单（冲 10% 提交率）

### 3.1 核心设计洞察

**把「选队伍」做成表单的第一问。** WaterBomb 的 Blue/Yellow（首尔为 Green/Yellow）分队机制是它最独特的资产——购票时就选边，赛中进行水枪对抗。把它前置为表单问题，一举三得：

1. 游戏化 → 显著提升提交意愿（这是唯一能把自己和"又一个音乐节注册页"区分开的点）
2. 天然产出可分群数据 → 后续按 `team_blue` / `team_yellow` 分群发不同内容
3. 回答成本极低（二选一，不需要打字）→ 不拖累转化

### 3.2 表单字段（总计 2 个，不再多）

| 字段 | 类型 | 必填 | 理由 |
|---|---|---|---|
| Email | input[type=email] | ✅ | 唯一必须打字的字段 |
| Pick your team | radio: Blue / Yellow | ✅ | 游戏化 + 分群，零打字成本 |

> 每多一个字段，提交率掉 10–20%。年龄/国家/姓名一律不要 —— 需要的话在确认邮件里补。

### 3.3 转化杠杆清单

- 表单**首屏可见**（above the fold），移动端单列，CTA 按钮 ≥44px
- **只有一个 CTA**，不并列"了解更多 / 查看阵容"
- 首屏加载 **< 2s** → LP 必须静态化，不走 Mautic 动态渲染
- 社会证明：「X fans already picked their team」（数字来自真实提交数，无数据时不要编）
- 提交后即时反馈 + `svc1` 确认邮件
- 不做退出意图弹窗（移动端体验差，反而伤转化）
- 纯英文，无中文字符（含 `lang="en"`、字体、alt 文案）

### 3.4 资产复用（reuse-first）

**只做 1 个落地页 `LP_WB2026_SIGNUP_EN`，5 波共用，靠 utm 区分来源** —— 不做 5 个 LP。
（现有 spec 草案里 `/s/c1-en` … `/s/c5-en` 共 5 个 LP 是浪费，建议砍掉。）

---

## 4. Mautic 资产命名

| 类型 | 名称 | 说明 |
|---|---|---|
| Campaign | `CMP_WB2026_MAIN` | **1 个 campaign 承载 5 波**，不拆 5 个独立 campaign |
| Segment | `SEG_WB2026_GLOBAL_EN` | 海外英文受众（source=CSTS + locale=en_US） |
| Form | `FORM_WB2026_SIGNUP` | email + team 两字段 |
| Page | `LP_WB2026_SIGNUP_EN` | 唯一落地页 |
| Email | `EM_WB2026_C1_ANNOUNCE` | |
| Email | `EM_WB2026_C2_LINEUP` | |
| Email | `EM_WB2026_C3_LASTCALL` | |
| Email | `EM_WB2026_C4_RECAP` | |
| Email | `EM_WB2026_C5_WAITLIST` | |
| Email | `EM_WB2026_SVC1_CONFIRM` | 事务性，不占频控 |
| Tags | `wb2026_c1`…`wb2026_c5`、`wb2026_registered`、`wb2026_team_blue`、`wb2026_team_yellow`、`wb2026_confirmed` | |

---

## 5. 待修的两个代码缺陷（都需要你点头）

### 5.1 en_US 枚举值静默 miss

**现象**：`male` / `elite` / `overseas` 等英文值打不进中文 match 表，同画像中英两版打分差 0.31。
**方案（二选一）**：
- (a) match 表加英文别名：`gender: ["男","女","male","female"]`、`education: [..., "elite","other"]`
- (b) brief 抽取阶段做 en→zh 归一化

我倾向 **(a)**，改动小、不依赖 LLM 抽取稳定性。

### 5.2 缺 interest 维度

**方案**：新增 `interest` 字段，权重 **0.15**；为保持总权重 1.00，把 `education` 0.15→0.10、`industry` 0.15→0.10。
`YOUNG_TREND` 增加 `interest: ["音乐","娱乐","潮流","电竞"]`。
需同步改 `goal_intake.py`、`cockpit.py` 内联 JS、UI 表单三处。

### 5.3 （已提，待定）CORP_GRP 覆盖度副作用

留空=满分后，**定义字段少的包占便宜**。实测 `CSTS + 18-24 + L4` → `CORP_GRP(1.00/0.25)` 排在 `YOUNG_TREND(0.69/0.30)` 之前，尽管后者证据更强。
修法：排序引入 coverage 项（已定义字段占比）。**要不要动，你定。**

---

## 6. 需要你确认的清单

1. **时间窗/锚点**：选 A（LV 冲刺 + 转澳门候补）／ B（延到 11/16）／ C（维持原样）？→ 我推荐 **A**
2. **LV 站官方名称与年龄门槛**：是 "WaterBomb Las Vegas" 还是 "WaterBomb LA"？18+ 还是 21+？
3. **是否修 5.1 / 5.2 / 5.3**？（5.1 + 5.2 我建议一起做，5.3 可缓）
4. **确认后我再执行**：重写 `waterbomb_2026_strategy_spec.json` → 建 `LP_WB2026_SIGNUP_EN` → 推 Mautic（推送前会先把资产清单给你过一遍，不做删除动作）
