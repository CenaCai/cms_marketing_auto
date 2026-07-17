# PRD vs 当前实现 — 差异对照与原因说明

> 对照对象：`CRM + 全链路营销自动化平台 MVP PRD.md` ↔ `cms_marketing_auto` 当前代码（截至 commit `e6553f0`）
> 结论先行：**数据模型与 PRD 高度对齐（约 85% 的表结构已落地）；差异主要在「环境选型」和「后期阶段(V2/V3/V4)的 UI 与真实渠道」，核心 V0/V1 链路已跑通。**

状态图例：✅ 已实现 ｜ 🟡 部分（代码层有 / 仅默认桩 / UI 待完善） ｜ 🔴 缺失 ｜ ➕ 超出 PRD（额外实现）

---

## 一、环境 / 技术选型差异（最大的一类区别）

| PRD 建议 | 当前实现 | 差异 | 为什么 |
|---|---|---|---|
| PostgreSQL | **SQLite**（`provider="sqlite"`） | 🟡 | 为本地/演示**零外部依赖自包含**运行；schema 顶部已注明「部署时切回 postgresql + 还原 enum/array」。所有 enum/数组已用 String + JSON 字符串兼容。 |
| Prisma ORM | Prisma 5.22 | ✅ | 一致。 |
| Redis + BullMQ 队列 | **内存队列（MemoryQueue）**，BullMqQueue 代码已存在但默认不启用 | 🟡 | 默认 `queueDriver=memory`，无需 Redis 即可跑通发送/工作流；生产切 Redis 只需改 env + 把 processor 搬到 worker。 |
| S3 兼容存储 | **未接（mock/本地）** | 🔴 | 模板图片、附件等目前走本地/占位，未接对象存储。 |
| shadcn/ui | Tailwind + 自写组件 | 🟡 | 视觉风格对齐，未引入 shadcn 组件库。 |
| 多组织 + 组织切换 | **单组织（种子数据），无组织切换 UI** | 🟡 | `OrganizationMember` 已支持「一用户多组织」，但后台无组织列表/切换页，仅 seed 一个组织。 |
| 注册入口 | **已关闭（你明确要求）** | 🔴 | 按你之前指令移除注册、仅 admin 开通账号。 |
| 角色 = 4 档固定 | **模块×CRUD 权限矩阵**（4 档 role 仅作为 model 默认值） | 🟡 | PRD 既要「角色」又要「勾选下级功能」，当前用细粒度矩阵实现（SUPER_ADMIN 始终放行），比纯 4 档更细，但无独立「Org Admin / Viewer」分档 UI。 |

---

## 二、功能差异（按 PRD 章节）

### V0 基础设施

| PRD 功能 | 状态 | 说明 | 为什么 |
|---|---|---|---|
| 注册/登录 | 🟡 | 登录✅；注册❌（关闭） | 你的明确要求。 |
| 组织管理（列表/详情/成员） | 🔴 | 无组织管理页，仅 `users` 页管本组织成员 | 单组织阶段未做多组织 UI。 |
| 一个用户多组织 + RBAC | 🟡 | 数据层支持；UI 与切换缺失 | 优先级后置。 |
| 成员邀请/禁用/删除 | ✅ | `users` 页支持创建/禁用/删除 + 权限矩阵 | 已实现。 |
| 联系人基础字段 + 状态 | ✅ | 姓名/邮箱/手机/国家/城市/语言/来源/状态/最近活跃 全部字段 + 4 状态 | 对齐。 |
| 联系人去重（邮箱/手机） | ✅ | `@@unique([org,email])`、`@@unique([org,phone])` | 对齐。 |
| 自定义字段（6 类型/启用/排序/必填） | 🟡 | **模型✅（text/number/date/boolean/select/multi_select）**；**管理 UI ❌**；联系人详情未渲染自定义字段 | 模型已就位，缺增删改 UI 与详情展示。 |
| 事件中心（6 类事件/属性/去重） | ✅ | `Event` 模型 + `POST /api/events` + 去重键 | API 写入✅。 |
| 事件写入方式：Webhook / API / SDK | 🟡 | **API 写入✅**；**入站 Webhook 接收❌**；SDK❌ | 只有「系统对外发 Webhook（Webhook 模型）」，没有「外部推数据进来的入站接收器」。 |
| 数据导入：CSV/Excel/API/Webhook | 🟡 | **CSV+Excel 上传✅**（去重+ImportJob 报告：成功/失败/重复数）；**字段映射 UI ❌**；**API/Webhook 入站❌** | 文件导入核心已通；映射步骤与入站通道未做。 |
| 导入结果报告/历史 | 🟡 | ImportJob 记录成功/失败/重复 + report JSON；**历史列表 UI ❌** | 数据有，前端未列。 |
| 发送服务：队列/失败重发/日志/限流/日上限/频控/黑名单/退订过滤 | 🟡 | **队列✅**（内存）、**自动过滤✅**（退订/黑名单/无联系方式/24h 频控5次，代码级）、**发送日志✅**、**失败记录✅**；**每日上限❌**、**真正重发循环⚠️**（失败仅记录，无自动重试 job）、**真实发出❌默认 mock** | 过滤与日志是真实逻辑；真实发送需配 SMTP/Twilio。 |
| 系统日志（操作/API/Webhook/发送/错误） | 🟡 | `SystemLog` 模型✅（5 类）；**统一日志查看页❌**（仅 SQL 查询有审计写入） | 模型与写入点有，缺聚合查看 UI。 |

### V1 联系人 + EDM/SMS

| PRD 功能 | 状态 | 说明 | 为什么 |
|---|---|---|---|
| 标签 CRUD + 手动/批量 + 复合筛选 | 🟡 | 列表/增删改✅；批量打标✅；`tags/filter` 端点存在，**「包含任一/全部/不包含」UI 待你试用确认** | 后端能力具备，前端筛选交互需验证。 |
| 分群：静态 + 动态 + 规则 | ✅ | `Segment` 静态/动态；`evaluateSegment` 真实按 rules 求值 | 对齐。 |
| 模板：EDM（变量/预览/测试发/复制/版本） | 🟡 | EDM✅（subject/html/变量/预览/AI生成）；SMS 类型✅；**测试发送❌**、**版本管理❌**、**复制⚠️** | 核心编辑可用，高级功能未做。 |
| Campaign：创建/目标分群/渠道/模板/时间/状态机 | ✅ | 全状态机 draft→scheduled→sending→sent/paused/failed/completed | 对齐。 |
| Landing Page / H5 编辑器 | 🔴 | **无页面、无模型** | PRD 标「一期轻量版」，尚未排期。 |
| 批量发送：预览人数 + 自动过滤 + 立即/定时/暂停/重试 | 🟡 | 按分群/标签/直接选人发送✅；定时✅（delayMs）；**发送前「预计人数拆解（有效邮箱/手机/退订/黑名/频控）预览 UI ❌** | 过滤逻辑在后端，前端未做人数拆解预览。 |
| 数据统计：打开/点击/退订/bounce/链接明细 | 🟡 | `track/open`、`track/click` 回执✅；`analytics` + `reports` 页✅（基础统计）；**bounce/退订独立统计 UI 较薄** | 基础闭环有，深度报表待补。 |

### V2 自动化 Workflow

| PRD 功能 | 状态 | 说明 | 为什么 |
|---|---|---|---|
| 可视化 Workflow（触发器/条件/动作/延迟/分支） | 🟡 | **引擎✅**：事件触发→动作序列→`wait` 延迟续跑；支持 send_email/sms/add_tag/remove_tag/join/leave_segment/call_webhook；分支以条件动作占位。**可视化拖拽编辑器❌**（仅 JSON 定义 + `workflows` 页） | 执行引擎真实可用，编辑体验是 JSON，非拖拽。 |
| 用户行为监控 + 时间线 + 自动更新标签 | 🟡 | 事件时间线数据✅；**「行为→标签」自动规则引擎❌**（如「浏览F1≥2次且未购→high_intent_f1」需手建 workflow 或手动打标） | 自动标签规则尚未做成可配置引擎。 |

### V3 AI 辅助运营

| PRD 功能 | 状态 | 说明 | 为什么 |
|---|---|---|---|
| AI 生成文案（输入主题→标题+正文） | 🟡 | **真实 OpenAI 兼容客户端✅**（填 Key 即用 DeepSeek/OpenAI；无 Key 走 mock 兜底，不报错） | 你确认保持 mock 默认。 |
| AI 推荐发送时间 / AI 分群 / AI Workflow 推荐 / AI 复盘 | 🟡 | 对应路由存在（`ai/send-time`、`ai/segment`、`ai/workflow`、`ai/analyze`），**多为规则/mock 雏形，未接真实模型深度** | V3 阶段，待接模型与数据打磨。 |
| AI 爬虫引流（合规采集） | 🔴 | 未实现 | 合规风险高，且非 MVP 核心，未排期。 |

### V4 多渠道

| PRD 功能 | 状态 | 说明 | 为什么 |
|---|---|---|---|
| 联系方式多渠道（WhatsApp/FB/Telegram/X/Email/Phone/AppID） | 🟡 | `ContactChannel` 模型✅；**写入/展示 UI ❌** | 模型在，渠道管理 UI 未做。 |
| 发送渠道扩展（WhatsApp/FB/App Push/...） | 🔴 | 仅 EMAIL/SMS 有 provider（且默认 mock）；WhatsApp/Push 等无 provider | V4 阶段，需各渠道凭证与 SDK。 |

### 你后续追加的需求（超出原 PRD）

| 功能 | 状态 | 说明 |
|---|---|---|
| **SQL 精准圈人**（写 SELECT 圈人→保存分群→群发） | ✅➕ | 我们新增 `POST /api/query`（租户隔离 + 只读沙箱）+ `/query` 页，端到端跑通。PRD 仅提「按属性/行为」，未提裸 SQL。 |
| **Mautic 标签体系集成** | 🟡➕ | 适配器接缝已就位（真实 REST / Mock 切换），默认 stub，待你给实例。PRD 未提及 Mautic。 |

---

## 三、差异的根因归类（为什么和 PRD 不一样）

1. **本地自包含优先（环境类差异的主因）**
   SQLite、内存队列、mock 邮件/SMS/AI —— 都是为了「一条命令起项目、无需任何外部服务/密钥」。`smtp.ts`/`twilio.ts`/`bullmq.ts`/`openai.ts` 真实实现都已写好，**填配置即生效**，不是没做，是默认关。

2. **PRD 是 V0→V4 的远期蓝图，实现聚焦 MVP（功能类差异的主因）**
   已做的是 V0 账号/联系人/事件/导入 + V1 标签/分群/模板/Campaign/发送/统计 + V2 工作流引擎骨架。
   未做的是 V1 的 Landing Page、V2 的可视化编辑器与自动标签引擎、V3 的 AI 深度、V4 的多渠道 provider——都属于「后续阶段」。

3. **你的明确指令（人为差异）**
   - 关闭注册入口（仅 admin 开通）。
   - AI / Mautic 默认 mock/stub。
   - 追加了「SQL 圈人」「Mautic 集成」两项 PRD 没有的需求。

4. **范围/优先级未排到的（缺口）**
   自定义字段管理 UI、入站 Webhook/API 接收、导入字段映射 UI、组织切换 UI、系统日志聚合页、发送人数拆解预览、每日发送上限、自动重试 job、Landing Page、多渠道 provider。

---

## 四、建议的「补齐优先级」（若要追平 PRD）

**P0（让 MVP 真正可用，且几乎零成本）**
- 自定义字段管理 UI + 联系人详情渲染（模型已好）。
- 发送人数拆解预览（后端过滤已就绪，前端加一个统计面板）。
- 组织切换 / 多组织 UI（数据已支持）。

**P1（打通自动化闭环）**
- 「行为→标签」自动规则引擎（让 PRD §15.2 的映射自动跑）。
- Workflow 可视化编辑器（引擎已有，补 UI）。
- 入站 Webhook / API-Key 接收（事件与联系人 ingestion 闭环）。

**P2（追平 V3/V4）**
- 真实渠道凭证接入（SMTP/Twilio 已在，接 WhatsApp/Push）。
- AI 深度（接真实模型做分群/复盘/Workflow 推荐）。
- Landing Page 轻量编辑器。

**环境升级（上线时）**
- SQLite→PostgreSQL；memory→BullMQ+Redis；接 S3；切真实 provider。
