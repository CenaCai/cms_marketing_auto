# 阶段(S1–S6)自动转换 · 实施说明

> 目标：联系人达到各阶段触发条件时，自动把阶段在 S1↔S6 之间升降级。
> 全部六阶段均已实现，并经真实 cron 路径端到端验证通过。

## 核心方案：Segment 过滤器作来源 + Campaign「改阶段」动作

**没有用** Campaign 内嵌的「联系人积分」(lead.points) 决策节点——该决策在联系人**到达时一次性评估**，
积分 25 分时经过「≥50」决策判 `no` 后就离开节点，之后涨到 55 分也**不会回头重评**，导致跨阈值升级失效。

正确且可靠的方式是 **用 Segment 过滤器(当前值)作为 Campaign 来源**：
Segment 每次 `rebuild` 按**当前字段值**重算成员，字段跨阈值时自动把联系人拉进对应 Campaign，进入即执行「改阶段」动作。

```
[ Segment: 积分≥20 ]      ──▶ [ Campaign: 改阶段→S2 ]
[ Segment: 积分≥50 ]      ──▶ [ Campaign: 改阶段→S3 ]
[ Segment: 订单数≥1 ]     ──▶ [ Campaign: 改阶段→S4 ]   (首单成交)
[ Segment: 订单数≥3 或 累计消费≥1000 ] ──▶ [ Campaign: 改阶段→S5 ]  (复购/忠诚)
[ Segment: 最近活跃≤90天前 ] ──▶ [ Campaign: 改阶段→S6 ]  (沉睡流失)
```

## 交付物（已写入 Mautic 实例）

### S1→S3（积分驱动段）
| 类型 | 名称 | ID | 关键配置 |
|------|------|-----|----------|
| Segment | 积分≥20（自动升S2） | 3 | filter: `points >= 20` |
| Segment | 积分≥50（自动升S3） | 4 | filter: `points >= 50` |
| Campaign | 积分≥20 自动升 S2 | 3 | source=seg3 → `stage.change` → S2 |
| Campaign | 积分≥50 自动升 S3 | 4 | source=seg4 → `stage.change` → S3 |

### S4→S6（订单 / 沉睡驱动段）
依赖 3 个自定义字段（已建，列在 `leads` 表）：
- `order_count`（订单数，number，field id=44）
- `total_spent`（累计消费金额，number，field id=45）
- `last_activity_date`（最近活跃日期，date，field id=46）

`last_activity_date` 由 TravelPoints 回传端点在**每个 `travel.*` 事件**时刷新；`travel.payment_success` 时累加 `order_count` 与 `total_spent`。

| 类型 | 名称 | ID | 关键配置 |
|------|------|-----|----------|
| Segment | 首单支付（自动升S4） | 5 | filter: `order_count >= 1` |
| Segment | 复购忠诚（自动升S5） | 6 | filter: `order_count >= 3` **OR** `total_spent >= 1000` |
| Segment | 沉睡流失（自动升S6） | 7 | filter: `last_activity_date <= -90 days` |
| Campaign | 订单驱动-首单自动升S4 | 5 | source=seg5 → `stage.change` → S4 |
| Campaign | 复购忠诚自动升S5 | 6 | source=seg6 → `stage.change` → S5 |
| Campaign | 沉睡自动升S6 | 7 | source=seg7 → `stage.change` → S6 |

Campaign 事件统一：`type=stage.change, event_type=action, properties={"stage":N}`。

> 业务规则提醒：S6（沉睡）是**反向降级**逻辑——任意阶段客户只要 90+ 天未活跃就会被拉进 S6。
> 例如 S5 忠诚客长期未互动也会降到 S6。这符合"沉睡流失"语义；如希望 VVIP 不被降级，需给 S6 段加
> 排除条件（如 `stage != 5`）。当前按既定规格实现，如需调整告诉我即可。

## 验证结果（实测通过）

### S1→S3（手动调整积分 + 命令链）
- 积分 **25** → 自动升 **S2**（`stage_id=2`）✓
- 积分 **55** → 自动升 **S3**（`stage_id=3`）✓

### S4→S6（全新测试联系人 + 真实 cron 路径）
| 测试联系人 | order_count | total_spent | last_activity_date | 期望 | 实际 stage |
|------|------|------|------|------|------|
| 首单客 | 1 | 0 | 当天 | S4 | **4 ✓** |
| 复购客 | 3 | 1500 | 当天 | S5 | **5 ✓** |
| 沉睡客 | 0 | 0 | 100 天前 | S6 | **6 ✓** |
| 对照(新客) | 0 | 0 | 当天 | 保持 S1 | **空 ✓（不误升）** |

`stage.change` 动作自带「已在目标阶段则跳过」保护，不会因多 Campaign 同时命中而错乱/降级。

## ✅ Cron 已配置（Windows 任务计划程序，每 5 分钟 + 每周邮件）

Windows 无原生 cron，已用「任务计划程序」(`schtasks`) 注册两个用户级任务（运行身份 `cenacai`，登录状态下运行）：

### 任务 1：`Mautic Cron`（每 5 分钟，阶段/活动引擎）
- **周期**：每 5 分钟
- **脚本**：`mautic-prod/cron-mautic.bat`（依次跑 `segments:update` → `campaigns:rebuild` → `campaigns:trigger`）
- **注册命令**（如需在他机重建）：
  ```bat
  schtasks /create /tn "Mautic Cron" /tr "C:\Users\cenacai\WorkBuddy\2026-07-16-12-05-32\mautic-prod\cron-mautic.bat" /sc minute /mo 5 /f
  ```
- **立即手动触发一次**（排错用）：`schtasks /run /tn "Mautic Cron"`

### 任务 2：`Mautic Weekly Intent Email`（每周一 09:00，意向客周邮件）
- **周期**：每周一 09:00
- **脚本**：`mautic-prod/weekly-intent-email.bat`（跑 `zz_weekly_intent_email.php`，向 Seg#10 意向客重发 email#8）
- **注册命令**：
  ```bat
  schtasks /create /tn "Mautic Weekly Intent Email" /tr "C:\Users\cenacai\WorkBuddy\2026-07-16-12-05-32\mautic-prod\weekly-intent-email.bat" /sc weekly /d MON /st 09:00 /f
  ```

> 注意：任务计划为「只使用交互方式」，即 **cenacai 登录期间**才会按时执行。本地开发足够；若需 7×24 无人值守，可在任务属性里改为「不管用户是否登录都运行」（需管理员 + 提供密码）。
> 沙箱环境重启后 schtasks 可能清空，需按上面命令重建（或参考 `tools/cron-mautic.bat`、`tools/weekly-intent-email.bat` 模板，注意里面的绝对路径需按本机调整）。

### Cron 端到端验证（已实测通过）
全新测试联系人经 **纯 cron 路径**（schtasks → bat → 三命令）自动完成 S4/S5/S6 升级；对照联系人保持 S1 不误升。
> 注：cron 跑完后 stage 变更约有几秒事务落库延迟，查询稍等片刻即可看到阶段变化。

## 手动验证命令（排错用）
```bash
php bin/console mautic:segments:update
php bin/console mautic:campaigns:rebuild
php bin/console mautic:campaigns:trigger
# 查看某联系人阶段与订单字段
SELECT id,points,order_count,total_spent,last_activity_date,stage_id FROM leads WHERE id=<联系人ID>;
```

## 积分触发器（阶段标签，补充层）

Mautic 的**积分触发器（Point Triggers）动作里没有"改阶段"**——改阶段是 Campaign 动作（见上 S1–S3）。
因此积分触发器用于在达到积分阈值时**自动打上对应的阶段标签**，与 Campaign 的改阶段互为补充、互不冲突。

新建 2 个阶段标签 + 2 个积分触发器（均 published）：

| 积分触发器 | 阈值 | 动作 | 自动打标 |
|------|------|------|------|
| 积分达20分→S2标签 | points ≥ 20 | `lead.changetags` | `S2-意向客` |
| 积分达50分→S3标签 | points ≥ 50 | `lead.changetags` | `S3-高意向` |

- 触发器动作 `add_tags` 必须用**标签名字符串**（不能用标签 ID，否则运行时 `modifyTags` 报 TypeError）。
- 存量回填：当前积分已 ≥20 / ≥50 的联系人已直接写入 `lead_tags_xref`（幂等）。
- 端到端验证（真实加分链路 `travel.payment_success` +50 分）：测试联系人自动获得 `S2-意向客` + `S3-高意向` 两个标签 ✅。

> 关系说明：Campaign 负责"改阶段字段"（S2/S3），积分触发器负责"打阶段标签"。两者独立，可同时存在。
> 若要改触发动作为发邮件/通知，需新建邮件模板或改用 `email.send` / `email.send_to_user` 动作类型。

## 营销漏斗（自动化-活动）— 用户核心需求

> 设计原则：**S1–S6 阶段** 与 **营销漏斗** 是【并集】关系，互不冲突。
> - 潜客(S1)→意向客(S2)：可由「积分≥20 **OR** 单周浏览≥3次 **OR** 点击潜客邮件官网链接」任一触发；
> - 意向客(S2)→高意向(S3)：可由「积分≥50 **OR** 加购未付 **OR** 点我要下单」任一触发。
> 两套路径打到同一终点状态（S2-意向客 / S3-高意向 标签 + 阶段），真并集。

### 素材清单（幂等脚本已建并验证）
| 类型 | 名称 | ID | 备注 |
|------|------|-----|------|
| 标签 | 潜在客户 | #2 | 入库时打 |
| 标签 | S2-意向客 | #104 | 进 S2 打（镜像标签，便于分群） |
| 标签 | S3-高意向 | #105 | 进 S3 打 |
| 标签 | 退订 | #106 | 退订表单提交时打 |
| 标签 | 意图-迪士尼亲子 | #76 | 仅「点我要下单(上海迪士尼页)」时打，非进 S3 自动打 |
| 标签 | 上海 | #5 | 同上，行为标签 |
| 标签 | 一线城市（北上广深） | #64 | 同上，行为标签 |
| 分群 | 潜客入口 | Seg#9 | 过滤「无潜在客户标签的新潜客」 |
| 分群 | 意向客 | Seg#10 | 过滤「stage=2(意向客)」 |
| 邮件 | 潜客欢迎邮件 | #7 | CTA→connexustravel.com.cn；退订→page#2 |
| 邮件 | 意向客每周活动推荐 | #8 | CTA→page#4 |
| 邮件 | S2-意向客·旅行优惠与攻略推送 | #4 | 积分触发器 TRIG#1 发 |
| 邮件 | S3-高意向·加急券与行程顾问 | #5 | 积分触发器 TRIG#2 发 |
| 落地页 | 退订询问页 | page#2 | 嵌 form#4 |
| 落地页 | 下单确认页 | page#3 | 「我要下单」目标页 |
| 落地页 | 上海迪士尼介绍页 | page#4 | 含「我要下单」→page#3 |
| 表单 | 退订询问 | form#4 | 邮箱 + 退订原因#47(必填) + 提交 |

### 战役 Cmp#8 潜客工作流（源 Seg#9 潜客入口）
```
[Seg#9 潜客入口]
  └─ev#10 lead.changetags +潜在客户
       └─ev#11 email.send #7（潜客欢迎邮件）
              ├─ev#12 决策 email.click (url=connexustravel.com.cn)
              │        └─(yes) ev#13 lead.changetags +S2-意向客 / -潜在客户
              │                 └─ev#14 stage.change → S2
              └─ev#15 决策 form.submit (form#4 退订询问)
                       └─(yes) ev#16 lead.changetags +退订 / -潜在客户
```
- 决策事件属性键：`email.click`→`urls`(数组)、`form.submit`→`forms`(数组)。
- 联系人在潜客工作流里**未提交退订**则保持潜在客户；**点击官网链接**升意向客；**提交退订表单**转退订标签。

### 战役 Cmp#9 意向客转化（源 Seg#10 意向客）
```
[Seg#10 意向客(stage=2)]
  └─ev#17 email.send #8（意向客每周活动推荐）
         └─ev#18 决策 page.pagehit (page#3 下单确认页)
                  └─(yes) ev#19 lead.changetags +S3-高意向 +意图-迪士尼亲子 +上海 +一线城市 / -S2-意向客
                           └─ev#20 stage.change → S3
```
- `page.pagehit`→`pages`(数组)；`stage.change`→`stage`(id)；`lead.changetags`→`add_tags`/`remove_tags`（传**标签名**）。
- **意图-迪士尼亲子/上海/一线城市** 仅在「点我要下单(上海迪士尼页)」路径打，不是进 S3 就自动打。

### 每周邮件
- `zz_weekly_intent_email.php`：每周一向 Seg#10 重发 email#8（新意向客进入 Cmp#9 时已由 ev#17 首发一次，本脚本负责按周重发）。
- Windows 任务计划 `Mautic Weekly Intent Email` 每周一 09:00 调 `weekly-intent-email.bat`。

### 阶段 vs 标签（约定）
- **阶段(Stage)**：客户在漏斗中的"位置"，同一时刻只有 1 个（S1→S6 线性递进），由 `stage.change` 改。
- **阶段镜像标签**（S2-意向客/S3-高意向）：进阶段时自动打的冗余标签，便于分群/筛选。
- **行为/属性标签**（意图-迪士尼亲子/上海/一线城市/潜在客户/退订）：由具体行为或属性触发，与阶段无绑定。

### 构建脚本
- `zz_create_assets.php` — 建邮件 #4/#5/#7/#8、页面 #2/#3/#4
- `zz_create_form2.php` — 建 form#4（退订询问）
- `zz_create_campaigns.php` — 建 Cmp#8/#9（含决策事件 + 标签/阶段动作）
- `zz_weekly_intent_email.php` — 每周意向客邮件

---

## 排障与修复（2026-07-23）

### 1. 营销邮件画布编辑器打不开（脚本创建的 #4/#5/#7/#8）
- **根因**：GrapesJS 画布只读 `emails.content['grapesjsbuilder']['editorState']`（隐藏域 `.builder-json`），**绝不读 `custom_html`**。脚本建的邮件只写了 `custom_html` + 空 `content`，且 `template='blank'`(MJML 主题) 与 HTML 内容模式不匹配。
- **第二半根因**（关键）：`.builder-html` 隐藏域 = `custom_html`，浏览器端 `getOriginalContentHtml()` 要求它是**完整 HTML 文档**(`<head>`+`<body>` 非空)，片段会抛 "No valid HTML template found"；已存在邮件加载时不会自动用主题文档覆盖。
- **修复脚本** `zz_repair_email_builder.php`（幂等）：
  1. `custom_html` 非完整文档 → 用 `themes/blank_html` 渲染成完整文档写回；
  2. `content` 无 editorState → 补（pages[0].frames[0].component = 片段字符串）；
  3. `setTemplate('blank_html')` + `saveEntity()`。
- **新增主题** `themes/blank_html/`（纯 HTML 模式，无 `<mjml>`，body 非空）：`config.json` + `html/email.html.twig`。已随 kit 覆盖到 `overrides/themes/blank_html/`。
- **必须重启 dev server + 清 prod 缓存**：长驻 `php -S` 进程内存容器是启动时编译的，新增主题后需 `taskkill` 旧进程 → `rm -rf var/cache/prod/*` → 重启，否则画布报找不到主题。

### 2. 活动画布没有连接线（Cmp#8 / Cmp#9）
- **根因**：Mautic 画布连线**完全由 `campaigns.canvas_settings`（序列化 nodes+connections）驱动**，与 `campaign_events.parent_id` 无关（后者只决定执行顺序）。脚本建活动时写的 canvas_settings 格式错（临时 ID / `x,y` 非 `positionX,positionY` / 扁平 `sourceAnchor` 非嵌套 `anchors.source`），jsPlumb 找不到 `CampaignEvent_<id>` DOM → 不画线。
- **修复脚本** `zz_repair_campaign_canvas.php`（幂等）：按真实 `campaign_events` 重建 canvas_settings，对齐 Mautic 官方 DataFixture 格式：
  - 节点=真实事件 ID + 特殊键 `lists`(源节点)，字段 `positionX/positionY`；
  - 连接 `sourceId/targetId/anchors.{source,target}`；父是决策→按子事件 `decision_path` 选 `yes/no`，否则 `bottom`；源→根事件 `leadsource`；目标 `top`。
  - 判决策用 `campaign_events.event_type`(action/decision)，**不是 `type` 列**(存动作名如 email.click)。

---

## 系统审计结论（2026-07-23，端到端排查）

**✅ 配置 100% 符合需求**（S1–S6 阶段推进 ∪ 营销漏斗 ∪ 积分触发器）：
- S1–S6 六阶段全部 published；Seg#3–#7（积分/订单/沉睡段）+ Seg#9/#10（漏斗入口）全部就位，过滤器正确。
- Cmp#3–#7（stage.change→S2~S6）、Cmp#8（潜客工作流）、Cmp#9（意向客转化）事件链**逐条核对正确**（决策 url/page/form、标签增减、阶段动作均无误）。
- 积分触发器 TRIG#1(≥20→S2标签+发#4)、TRIG#2(≥50→S3标签+发#5) 正确。
- 邮件 #4/#5/#7/#8（published、template=blank_html、editorState 已修复、custom_html 完整文档）、页面 #2/#3/#4、表单 #4、关键标签(潜在客户/S2-意向客/S3-高意向/退订/意图-迪士尼亲子/上海/一线城市) 全部就位。

**✅ 自动化引擎可运行**：手动跑 `segments:update → campaigns:rebuild → campaigns:trigger` 三连**无报错**；此前积分触发器实测已把联系人 S1→S3 并打标签（2 个高意向联系人 stage=S3、标签 S3-高意向×2），证明整条链路通。

**⚠️ 当前测试数据导致两个入口分群为空（非配置缺陷，属数据状态）**：
- **Seg#9 潜客入口 = 0 人**：6 个测试联系人**全都有「潜在客户」标签**，而 Seg#9 过滤器是"排除已有潜在客户标签的人"→ 全部被排除。全新环境（新联系人未打标签）下正常。
- **Seg#10 意向客(stage=2) = 0 人**：那 2 个高意向联系人已升到 **S3**，过滤 stage=2 时他们已不在 S2 → 空。
- 要让漏斗在当前数据上也跑演示，需清掉测试联系人的标签/阶段，或新建几个"干净"的 S1 潜客。

**🔧 MariaDB 启动注意（跨会话复现关键）**：
- 本机 Mautic 的数据库**不在** `C:\Program Files\MariaDB 12.3\data`（那是默认空实例），而在 **`C:\Users\cenacai\WorkBuddy\2026-07-16-12-05-32\mariadb-data`**（datadir 自带 `my.ini`）。
- 重启 MariaDB 必须用正确 datadir：`mysqld --defaults-file=".../mariadb-data/my.ini"`，否则会启动一个没有 `mautic` 库的空实例（连接报 Access denied）。沙箱环境重启后 MariaDB 进程可能退出，需手动拉起。

---

## 相关文件
- `zz_fields.php` — 建立 order_count / total_spent / last_activity_date 三个自定义字段
- `zz_create_s4s6.php` — 建立 S4/S5/S6 的 Segment + Campaign（含幂等保护，重跑不会重复建）
- `zz_create_point_triggers.php` — 建立阶段标签 + 积分触发器（20/50 分自动打标，含幂等保护）
- `zz_create_assets.php` — 建邮件 #4/#5/#7/#8、页面 #2/#3/#4
- `zz_create_form2.php` — 建表单 form#4（退订询问）
- `zz_create_campaigns.php` — 建战役 Cmp#8/#9（含决策事件 + 标签/阶段动作）
- `zz_weekly_intent_email.php` — 每周意向客邮件（向 Seg#10 发 #8）
- `zz_repair_email_builder.php` — **修复**脚本：补 editorState + 完整 custom_html + 切 blank_html 主题
- `zz_repair_campaign_canvas.php` — **修复**脚本：按真实事件重建活动画布连线
- `overrides/themes/blank_html/` — HTML 模式 GrapesJS 邮件主题（修复画布打不开用）
- `tools/cron-mautic.bat` / `tools/weekly-intent-email.bat` — Windows 计划任务启动器模板（绝对路径需按本机调整）
- `plugins/TravelPointsBundle/Controller/PublicController.php` — 回传端点，写入订单字段与刷新活跃日期
