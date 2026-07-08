# cms_marketing_auto — CRM + 全链路营销自动化平台 (MVP Scaffold)

面向文娱 / 体育 / 票务 / 文旅业务的自研 CRM 与营销自动化平台 MVP 脚手架。  
基于 PRD 落地：**联系人中心 · 标签分群 · EDM/SMS 批量发送 · 事件中心 · 自动化 Workflow · AI 辅助运营 · 多渠道触达**。

技术栈：**Next.js 14 (App Router) + React + Tailwind CSS + Prisma + SQLite(本地/演示) / PostgreSQL(生产)**，异步任务走队列，所有外部能力（邮件/短信/存储/AI/爬虫）通过 **Adapter 接口**接入，默认 mock 零依赖可跑。

---

## 快速开始（本地 / 演示，零外部依赖）

```bash
# 1. 安装依赖
npm install

# 2. 配置环境变量（默认已为 SQLite + mock）
cp .env.example .env
#   可选：修改 JWT_SECRET

# 3. 初始化数据库（SQLite，自动建表）
npx prisma generate
npm run prisma:dbpush

# 4. 写入演示数据（默认组织 + 全权限管理员）
npm run db:seed

# 5. 启动
npm run dev
# 打开 http://localhost:3000 → /login
```

> 默认 `EMAIL_PROVIDER=mock`、`SMS_PROVIDER=mock`、`QUEUE_DRIVER=memory`、`AI_PROVIDER=mock`、`CRAWLER_ENABLED=false`，  
> 因此**除 SQLite 外无需任何外部服务**即可跑通端到端流程（发送/AI 走 mock 打印日志）。

### 默认管理员账户

| 项 | 值 |
| --- | --- |
| 账号 | `admin`（也可用邮箱 `admin@cms.local`） |
| 密码 | `csts2026` |
| 角色 | `SUPER_ADMIN`（全权限） |

登录入口：`/login`。如需自定义，修改 `prisma/seed.ts` 后重跑 `npm run db:seed`。

> 注：本地 `npm run dev` 默认监听 `http://localhost:3000`，可直接在本机浏览器访问管理后台。

---

## 目录结构

```
cms_marketing_auto/
├── prisma/schema.prisma          # 完整数据模型（PRD 全部实体）
├── src/
│   ├── lib/                      # db / auth(JWT+RBAC) / env / response / api-client
│   ├── integrations/             # ★ 三方开源接口层（本文核心）
│   │   ├── email/                # nodemailer(SMTP ✅) / SES / SendGrid (留桩)
│   │   ├── sms/                  # Twilio / Vonage / Aliyun (留桩)
│   │   ├── storage/              # S3 兼容 (留桩)
│   │   ├── queue/                # BullMQ+Redis (留桩) / 内存队列 ✅
│   │   ├── ai/                   # OpenAI / Anthropic / Ollama (留桩) / Mock ✅
│   │   └── crawler/              # Playwright (留桩, 合规受限) / Mock ✅
│   ├── services/                 # 业务逻辑（不依赖三方 SDK）
│   │   ├── contact / tag / segment / template / campaign
│   │   ├── event / send / analytics / workflow.engine / ai / import
│   └── app/
│       ├── api/                  # 全部 REST 接口（见下）
│       ├── login/                # 登录/注册页
│       └── (dashboard)/          # 管理后台 UI
├── THIRD_PARTY_INTEGRATIONS.md   # ★ 哪些用三方开源 + 接口清单
└── .env.example
```

---

## REST API 速览

| 域        | 路由                                                                                                                                          |       |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| 认证       | `POST /api/auth/register`、`/api/auth/login`、`GET /api/auth/me`                                                                              |       |
| 联系人      | `GET/POST /api/contacts`、`GET/PATCH/DELETE /api/contacts/[id]`、`POST/DELETE /api/contacts/[id]/tags`、`GET/POST /api/contacts/[id]/channels` |       |
| 标签       | `GET/POST /api/tags`、`PATCH/DELETE /api/tags/[id]`、`POST /api/tags/filter`                                                                  |       |
| 分群       | `GET/POST /api/segments`、`PATCH/DELETE /api/segments/[id]`、`GET/POST/DELETE /api/segments/[id]/members`、`POST /api/segments/[id]/evaluate`  |       |
| 模板       | `GET/POST /api/templates`、`PATCH /api/templates/[id]`                                                                                       |       |
| Campaign | `GET/POST /api/campaigns`、`GET/PATCH /api/campaigns/[id]`、`POST /api/campaigns/[id]/send`                                                   |       |
| 事件       | `GET/POST /api/events`、`GET /api/events/timeline/[contactId]`                                                                               |       |
| 发送/追踪    | `GET /api/send/tasks/[id]`、`GET /api/track/open`、`GET /api/track/click`                                                                     |       |
| 统计       | \`GET /api/analytics?channel=EMAIL                                                                                                          | SMS\` |
| 工作流      | `GET/POST /api/workflows`、`PATCH/DELETE /api/workflows/[id]`                                                                                |       |
| AI       | `/api/ai/copy`、`/api/ai/send-time`、`/api/ai/segment`、`/api/ai/workflow`、`/api/ai/analyze`                                                   |       |
| 爬虫       | `POST /api/crawler`（合规受限）                                                                                                                   |       |
| 导入       | `POST /api/import`（CSV / Excel）                                                                                                             |       |

鉴权：`Authorization: Bearer <token>`（注册/登录返回）。RBAC 角色：`SUPER_ADMIN / ORG_ADMIN / MARKETING_OPERATOR / VIEWER`。

---

## 阶段对照（PRD）

- **V0 基础设施**：账号权限(RBAC)、联系人中心、自定义字段、事件中心、数据导入、发送服务、系统日志 —— 已实现核心骨架。
- **V1 联系人+发送**：标签、分群、模板、Campaign、批量发送、数据统计 —— 已实现。
- **V2 自动化**：可视化/表单式 Workflow（Trigger→Condition→Action→Delay→Branch）、行为时间线、动态分群 —— 引擎已实现（表单式），可视化编辑器待补。
- **V3 AI 运营**：文案/分群/发送时间/Workflow 草案/复盘 —— 接口+Mock 已实现，真实大模型留桩。
- **V4 多渠道**：contact_channels 表 + WhatsApp/FB/Telegram/X/Push 通道 —— 数据模型与接口已留，provider 待接。

---

## 关键设计

1. **Adapter 隔离**：Service 层只依赖 `integrations/*/types.ts` 接口，切换三方服务只改 `.env` + 一个 `*.ts` 桩。详见 `THIRD_PARTY_INTEGRATIONS.md`。
2. **组织隔离**：所有查询强制 `organizationId = session.organizationId`。
3. **合规优先**：AI 爬虫默认关闭，真实爬取必须保留 `sourceUrl` 并走人工审核。
4. **可追溯**：发送日志、打开/点击追踪像素、失败重试、频控、退订/黑名单过滤。

---

## 部署到公网（获取可访问的 Web 地址）

本项目管理后台需要服务端（Next.js API Routes + 数据库），因此需要一个能跑 Node 的托管环境，**不能仅用静态托管**。

推荐路径（可拿到真实公网 URL）：

1. **数据库**：使用托管 PostgreSQL（如 Supabase / Neon / Railway），拿到 `DATABASE_URL`。
2. **把 schema 切回 PostgreSQL**（见 `prisma/schema.prisma` 顶部说明）：`provider = "postgresql"`，并将 `String` 枚举列与 JSON 字符串列恢复为枚举 / `Json` 类型（即 PRD 原始设计）。
3. **部署**：Vercel / Railway / Render 直接连该 Git 仓库，`npm run build` + `npm start`，环境变量填 `DATABASE_URL`、各 `*_PROVIDER` 与 `JWT_SECRET`。
4. **管理员**：部署后执行一次 `npx prisma migrate deploy && npm run db:seed` 即可得到 `admin / csts2026`。

> 本地 `npm run dev` 默认监听 `http://localhost:3000`，可在本机浏览器直接访问后台；如需团队/外部访问，按上述步骤部署到公网即可。

---

## 待办（非阻塞）

- [ ] 接入真实 Email/SMS/AI provider（按 `THIRD_PARTY_INTEGRATIONS.md` 步骤）
- [ ] BullMQ worker 独立进程（`scripts/worker.ts`）
- [ ] 可视化 Workflow 编辑器（前端）
- [ ] 动态分群定时刷新任务
- [ ] 落地页/H5 编辑器
- [ ] BI 看板（ClickHouse/BigQuery 后接）
