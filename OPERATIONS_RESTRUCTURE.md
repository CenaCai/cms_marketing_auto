# 运营流程重构蓝图（OPERATIONS RESTRUCTURE BLUEPRINT）

> 目标：以「运营人员操作流程」为项目骨架，重新梳理 `cms_marketing_auto` 的
> 信息架构、导航、数据模型与路线图。本文档逐项把你的流程映射到**当前代码真实状态**
> （已做 ✅ / 部分 🟡 / 缺失 ❌），并给出落地计划。
>
> 范围确认（已与用户拍板）：
> - 交付 = 蓝图 + 重排导航 + 实现关键缺口
> - SQL 精准圈人 = **真实 SQL 查询**（在 organizationId 隔离范围内执行）

---

## 1. 平台核心链路（Backbone）

```
数据录入 ─▶ 联系人管理 ─▶ 用户标签 ─▶ 用户分群 ─▶ 创建 Campaign
   ▲                                                      │
   │                                                      ▼
   └──────── 用户行为回流 ─▶ 自动更新标签 ─▶ 影响下一次营销 ◀┘
                                    │
                                    ▼
                        EDM / SMS / 多渠道发送
```

**统一用户资产**：不同渠道用户沉淀为 CRM 联系人（按 `source` 区分）
官网注册 / App 注册 / 活动报名 / 购票 / 线下导入 / 广告线索 / 合作方名单 / 达人导流。

**精细化营销**：除标签 + 分群外，支持 **SQL 查询**圈定目标人群后批量群发。

---

## 2. 你的流程 → 当前代码映射（现状核查）

### Step 0 · admin 创建运营账号 + 角色权限
| 你的要求 | 状态 | 证据 |
|---|---|---|
| 系统管理 / 市场营销 / 报表查看 三档 | 🟡 | `auth.ts` 已有 `SUPER_ADMIN / ORG_ADMIN / MARKETING_OPERATOR / VIEWER` 四档 + `ROLE_RANK`；需收敛映射为你的三档语义 |
| 模块×CRUD 细粒度权限 | ✅ | `permissions.ts` + `UserPermission` 模型 + `users/page.tsx` 勾选矩阵 |
| admin 开通运营账号 | ✅ | `users/route.ts` POST + `user.service.ts createUser` |

### Step 1 · 登录
✅ `auth/login` 支持用户名/邮箱；JWT；`Sidebar` 含「账号管理」。

### Step 2 · 配置联系人字段
| 基础字段（姓名/邮箱/手机/国家/城市/语言/来源/状态/最近活跃） | ✅ | `Contact` 模型含全部基础列 |
| 自定义字段（感兴趣活动类型/预算/是否达人…） | 🟡 | `CustomField` + `CustomFieldValue` 模型已就绪；**缺自定义字段管理 UI**（增删改/排序/类型） |

### Step 3 · 数据录入 / 导入
| CSV 导入 | ✅ | `import/route.ts` + `import.service.ts parseCsv` |
| Excel 导入 | ✅ | `parseExcel`（base64） |
| API 写入（单条/批量联系人） | 🟡 | `contacts/route.ts` POST 单条；缺「批量 API 写入」收敛入口 |
| Webhook 写入 | ❌ | 无入站 Webhook 接收联系人端点（`Webhook` 模型仅用于出站） |
| 字段映射 UI | 🟡 | 后端 `ContactFieldMap` 支持；前端导入弹窗需补齐映射交互 |
| 去重规则（邮箱/手机相同→合并；两者皆空→不导入） | 🟡 | `importContacts` 已实现 `@@unique(email/phone)` 冲突处理 + `ImportJob` 统计；需把「去重规则选择」做成可配置 UI 并给出结果提示 |

### Step 4 · 清洗与检查
| 手动检查（邮箱/手机/国家城市/语言/退订/黑名单/重复/授权） | 🟡 | 联系人列表可展示，缺「清洗视图/校验提示」 |
| 发送前自动过滤：退订/黑名单/无效联系/超频控 | 🟡 | `Contact.status ∈ {unsubscribed,bounced,blacklisted}` + 发送引擎需补「频控」逻辑（`SendTask` 尚未含 rate-limit） |

### 打标签（三类来源）
| 4.1 按属性（country/language/interest/source → 标签） | 🟡 | 标签存在；缺「按属性批量自动打标」向导 |
| 4.2 按行为（事件→标签规则） | ❌ | `Event` 模型 + `events/route.ts`  ingestion 已就绪，但**缺「行为→标签」规则引擎**（如 浏览F1≥2且未购买→high_intent_f1） |
| 4.3 手动批量打标 | ✅ | `tags/bulk` + 联系人列表勾选 |

### Step 5 · 用户分群
| 静态分群（手动加人） | ✅ | `Segment.type=static` + `ContactSegment` + 分群页「勾选入组」 |
| 动态分群（条件自动更新） | ✅ | `Segment.type=dynamic` + `rules` JSON + `segment.service.evaluateSegment` + `/segments/[id]/evaluate` |
| 动态规则示例（标签含+浏览过+未购买+邮箱active+未退订） | 🟡 | `evaluateSegment` 支持 `tag / status / eventType` 条件，但需确认「未购买」「未退订」否定条件与组合 AND/OR 的完整覆盖 + 前端规则编辑器 |

### Campaign + 多渠道发送
| 创建 Campaign | ✅ | `campaigns/route.ts` |
| EDM / SMS / WhatsApp 等多渠道 | 🟡 | `Campaign.channel` 支持多值；`ContactChannel` 模型就绪；实际发送仅 EMAIL/SMS 有 provider 接缝（`integrations/email`），WhatsApp 待接 |
| 一键全选 / 按标签批量发送 | ✅ | `campaigns/[id]/send` 接收 `tagIds` + `contactIds` |

### 行为回流 + 自动更新标签 + 影响下一次营销
| 行为事件写入（Register/Login/Browse/Purchase/Refund/Custom） | ✅ | `events/route.ts` POST + `Event.eventType` |
| 打开/点击回执 | ✅ | `track/open` + `track/click` |
| 行为→自动打标签 | ❌ | 见 4.2（缺规则引擎） |
| 影响下一次分群/发送 | 🟡 | 动态分群可引用标签/事件，闭环依赖上面规则引擎 |

### 精细化营销 · SQL 精准圈人
| 运营写 SQL 圈人后批量群发 | ✅ | 已实现：`POST /api/query`（SELECT-only + `CURRENT_ORG` 隔离 + 防注入/多语句/注释 + 限行 5000 + 审计）+ `/query` 页（写 SQL → 预览命中 → 一键保存为分群，再于活动页群发）。已端到端验证。 |

---

## 3. 目标信息架构（导航重排）

把侧边栏从「功能罗列」改为「沿运营闭环分组」：

```
📥 数据资产
   ├─ 联系人        （字段配置 / 导入 / 清洗校验）
   ├─ 标签
   ├─ 分群          （静态 + 动态规则编辑器）
   └─ SQL 精准圈人   （写 SELECT → 预览命中 → 批量群发）   [新增]
📣 营销
   ├─ 模板          （AI 助手 / 图片 / 预览）
   ├─ 活动 Campaign （创建 / 全选 / 按标签发送）
   └─ 发送任务       （SendTask 队列 / 频控 / 日志）
⚙️ 自动化
   ├─ 事件中心       （Event 时间线 / 来源）
   ├─ 行为→标签规则  [新增规则引擎 UI]
   └─ 工作流 Workflow
📊 分析
   └─ 报表 Reports   （只读角色主屏）
🛠 系统
   ├─ 账号与权限     （三档角色 + 模块×CRUD 矩阵）
   ├─ 集成          （Mautic / Webhook 入站 / API Key）
   └─ 设置          （邮件 SMTP / AI / Mautic）
```

---

## 4. 数据模型映射：你的 SQL 示例 → 当前 Schema

你的示例：
```sql
SELECT u.user_id, u.email FROM user_profile u
WHERE u.country='UAE' AND u.interests LIKE '%Football%'
  AND u.is_email_reachable=1
  AND u.user_id IN (SELECT user_id FROM user_behavior WHERE action_type='view' AND event_name='F1_Event' AND action_date>=...)
  AND u.user_id NOT IN (SELECT user_id FROM order_table);
```

映射：
| 你的表/列 | 本项目 | 备注 |
|---|---|---|
| `user_profile` | `Contact` + `CustomFieldValue` | 基础列在 Contact；interests/预算等→CustomField |
| `u.country='UAE'` | `Contact.country` | 直接列 |
| `u.interests LIKE '%Football%'` | `CustomFieldValue(fieldKey='interests')` 或 `ContactTag` | 建议用标签 `interest_football` 更佳 |
| `u.is_email_reachable=1` | `Contact.status='active' AND email IS NOT NULL` | |
| `user_behavior` | `Event` | `eventType='BROWSE' AND eventName='F1_Event' AND occurredAt>=...` |
| `order_table` | `Event(eventType='PURCHASE')` 或新增 `Order` 模型 | 当前用 Event 表示购买 |

**SQL 查询服务设计（待实现）**：
- 端点：`POST /api/query`  `{ sql }` → 在 `WHERE organizationId = :orgId` 强制注入的前提下执行只读查询。
- 安全：白名单只允许 `SELECT`；解析 AST 拒绝 `INSERT/UPDATE/DELETE/DROP/`；禁止跨组织表；参数化 + 行数上限（如 5000）；审计写入 `SystemLog`。
- 返回：命中联系人 id/email 列表 → 可直接「基于此群发」。

---

## 5. 角色映射（你的三档 → 当前 RBAC）

| 你的角色 | 映射 | 权限 |
|---|---|---|
| 系统管理 | `SUPER_ADMIN` / `ORG_ADMIN` | 成员、客户、标签、分群、模板、Campaign 全模块×CRUD |
| 市场营销 | `MARKETING_OPERATOR` | contacts/tags/segments/templates/campaigns/ai 的 create/edit；reports view |
| 报表查看 | `VIEWER` | 仅 reports（只读）+ 各模块 view |

实现：在 `users/page.tsx` 角色下拉收敛为你的三档文案；底层仍用 `ROLE_RANK` + `UserPermission` 矩阵做细粒度控制。

---

## 6. 差距与分阶段路线图

### Phase A · 骨架对齐（导航 + 配置面）
- ✅ 重排 `Sidebar` 为 §3 分组结构（数据资产/营销/自动化/分析/系统）
- 🟡 自定义字段管理 UI（增删改/类型/排序）串起 `CustomField`
- 🟡 导入弹窗补齐：字段映射 + 去重规则选择 + 成功/失败/重复结果提示
- 🟡 角色三档文案收敛 + 报表查看角色主屏

### Phase B · 精准圈人（SQL + 可视化）
- ✅ `POST /api/query` 只读 SQL 执行（租户隔离 + 安全沙箱 + 限行 + 审计）
- ✅ SQL 圈人页：写 SQL → 预览命中数/样例 → 一键保存为分群（已端到端验证）
- （可选）等价的可视化条件构造器

### Phase C · 自动化闭环（行为→标签 + 接入）
- 行为→标签规则引擎 UI + 执行器（事件流入→自动打标）
- 入站 Webhook 接收联系人（`POST /api/webhooks/contacts` + 签名校验）
- 批量 API 写入收敛入口；发送频控逻辑

### Phase D · 多渠道与集成
- WhatsApp/渠道 provider 接缝
- Mautic 真实 REST 同步接通（需你提供实例）
- 报表完善（打开率/点击率/转化）

---

## 7. 建议下一步
按 Phase A → B → C → D 推进。Phase A/B 是「让运营流程跑顺 + 精准圈人」的关键，
建议优先。需要我先从哪一段落地？
