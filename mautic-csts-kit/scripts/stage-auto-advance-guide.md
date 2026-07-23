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

## ✅ Cron 已配置（Windows 任务计划程序，每 5 分钟）

Windows 无原生 cron，已用「任务计划程序」(`schtasks`) 注册用户级任务 `Mautic Cron`，每 5 分钟执行封装好的批处理脚本：

- **任务名**：`Mautic Cron`（运行身份 `cenacai`，登录状态下运行）
- **周期**：每 5 分钟
- **脚本**：`mautic-prod/mautic-cron.bat`（依次跑 segments:update → campaigns:rebuild → campaigns:trigger，日志写 `var/logs/mautic-cron.log`）
- **注册命令**（如需在他机重建）：
  ```bat
  schtasks /create /tn "Mautic Cron" /tr "C:\Users\cenacai\WorkBuddy\2026-07-16-12-05-32\mautic-prod\mautic-cron.bat" /sc minute /mo 5 /ru cenacai /f
  ```
- **立即手动触发一次**（排错用）：`schtasks /run /tn "Mautic Cron"`
- **查看运行日志**：`type var\logs\mautic-cron.log`

> 注意：任务计划为「只使用交互方式」，即 **cenacai 登录期间**才会按时执行。本地开发足够；若需 7×24 无人值守，可在任务属性里改为「不管用户是否登录都运行」（需管理员 + 提供密码）。

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

## 相关文件
- `zz_fields.php` — 建立 order_count / total_spent / last_activity_date 三个自定义字段
- `zz_create_s4s6.php` — 建立 S4/S5/S6 的 Segment + Campaign（含幂等保护，重跑不会重复建）
- `zz_create_point_triggers.php` — 建立阶段标签 + 积分触发器（20/50 分自动打标，含幂等保护）
- `plugins/TravelPointsBundle/Controller/PublicController.php` — 回传端点，写入订单字段与刷新活跃日期
- `mautic-cron.bat` — cron 三连命令封装
