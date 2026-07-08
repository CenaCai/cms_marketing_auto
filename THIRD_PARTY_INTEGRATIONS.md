# 三方开源依赖与接口预留（THIRD-PARTY INTEGRATIONS）

> 本文回答 PRD 中的要求：**「哪些模块会用到三方开源，并为其留好接口」**。
> 设计原则：**核心业务自研，外部能力一律走 Adapter（适配器）接口**；默认 `mock` 实现保证本地零依赖即可跑通全流程，切换真实三方服务只需在 `.env` 改配置并实现对应 `*.ts` 桩里的 `send()/scrape()` 等少数方法。

---

## 1. 总览表（哪些用三方开源、接口在哪）

| # | 模块 | 三方开源 / SDK | 当前状态 | 接口文件 | 切换方式 |
|---|------|----------------|----------|----------|----------|
| 1 | 数据库 ORM | **Prisma**（OSS） | ✅ 已实现 | `prisma/schema.prisma` | — |
| 2 | 邮件发送 | **nodemailer**(SMTP) / @aws-sdk/client-ses / @sendgrid/mail | 🟡 SMTP 已实现，SES/SG 留桩 | `src/integrations/email/*` | `EMAIL_PROVIDER` |
| 3 | 短信发送 | **twilio** / @vonage/server-sdk / 阿里云/腾讯云 SMS SDK | 🔲 全部留桩 | `src/integrations/sms/*` | `SMS_PROVIDER` |
| 4 | 对象存储 | **@aws-sdk/client-s3**（兼容 MinIO/COS/OSS/R2） | 🔲 留桩 | `src/integrations/storage/*` | `STORAGE_PROVIDER` |
| 5 | 异步队列 | **bullmq + ioredis**(Redis) | 🟡 内存队列已实现，BullMQ 留桩 | `src/integrations/queue/*` | `QUEUE_DRIVER` |
| 6 | AI 能力 | **openai** / @anthropic-ai/sdk / ollama(HTTP) | 🔲 全部留桩 | `src/integrations/ai/*` | `AI_PROVIDER` |
| 7 | AI 爬虫引流 | **playwright** / apify-client | 🔲 留桩（默认关闭） | `src/integrations/crawler/*` | `CRAWLER_ENABLED` |
| 8 | 密码哈希 | **bcryptjs**（OSS） | ✅ 已实现 | `src/lib/auth.ts` | — |
| 9 | Token | **jsonwebtoken**（OSS） | ✅ 已实现 | `src/lib/auth.ts` | — |
| 10 | 模板渲染 | **handlebars**（OSS） | ✅ 已实现 | `src/services/template.service.ts` | — |
| 11 | CSV 解析 | **papaparse**（OSS） | ✅ 已实现 | `src/services/import.service.ts` | — |
| 12 | Excel 解析 | **exceljs**（OSS） | ✅ 已实现 | `src/services/import.service.ts` | — |
| 13 | 校验 | **zod**（OSS） | ✅ 已装 | `src/lib/response.ts` | — |
| 14 | 前端 | **Next.js / React / Tailwind**（OSS） | ✅ 已实现 | `src/app/*` | — |

图例：✅ 已可直接用 ｜ 🟡 部分可用（mock + 一个真实实现）｜ 🔲 接口已留，待接真实 SDK

---

## 2. 集成架构（Adapter 模式）

```
   API Route
      │
      ▼
   Service 层 (src/services/*)   ← 纯业务逻辑，不依赖任何三方 SDK
      │
      ▼
   Integration Adapter (src/integrations/*)
      ├── 接口 (types.ts)        ← 稳定契约，跨 provider 不变
      ├── mock.ts                ← 开发默认，零依赖、打印日志
      ├── <provider>.ts          ← 真实实现 OR 留桩(throw 提示)
      └── index.ts (getXxx())    ← 按 env 选择 provider 的工厂
```

**关键点**：Service 层永远只依赖 `types.ts` 里的接口，不 `import` 具体 provider。新增一个短信通道（如腾讯云），只需：
1. `src/integrations/sms/tencent.ts` 实现 `SmsProvider`；
2. 在 `sms/index.ts` 的 `switch` 里加一行 `case "tencent"`；
3. `.env` 设 `SMS_PROVIDER=tencent`。
业务代码、其余服务一行都不用改。

---

## 3. 各模块接口说明

### 3.1 Email（`src/integrations/email`）
- 接口：`EmailProvider { send(msg: EmailMessage): Promise<EmailResult> }`
- 已实现：`SmtpEmailProvider`（nodemailer，可对接任意 SMTP：Gmail/Postfix/Mailgun/SES-SMTP/腾讯云邮件推送）。
- 留桩：`SesEmailProvider`（@aws-sdk/client-ses）、`SendGridEmailProvider`（@sendgrid/mail）—— 已写好落地步骤注释，补全 `send()` 即可。
- 环境变量：`EMAIL_PROVIDER=mock|smtp|ses|sendgrid`、`EMAIL_FROM`、`SMTP_*`、`AWS_*`、`SENDGRID_API_KEY`。

### 3.2 SMS（`src/integrations/sms`）
- 接口：`SmsProvider { send(msg: SmsMessage): Promise<SmsResult> }`
- 留桩：`TwilioSmsProvider`（海外+WhatsApp）、`VonageSmsProvider`、`AliyunSmsProvider`（国内）。
- 说明：国内短信（阿里云/腾讯云）需要**签名+模板审核**，接口已预留 `SIGN_NAME` / `TEMPLATE_CODE` 字段。

### 3.3 Storage（`src/integrations/storage`）
- 接口：`StorageProvider { put(input): Promise<StorageResult>; getUrl(key): string }`
- 用途：EDM 附件、落地页封面图、导入模板、AI 素材。
- 留桩：`S3StorageProvider`（@aws-sdk/client-s3），兼容 S3 / MinIO / 腾讯云 COS / 阿里云 OSS / Cloudflare R2。

### 3.4 Queue（`src/integrations/queue`）
- 接口：`QueueService { enqueue(type, data, {delayMs}); registerProcessor(type, handler); start(); close() }`
- 已实现：`MemoryQueue`（进程内单消费者，支持 `delayMs`——Workflow 的 Wait 节点直接复用）。
- 留桩：`BullMqQueue`（bullmq + ioredis + Redis）。生产建议把消费者放到独立 `scripts/worker.ts`，避免 Next.js 实例间任务分散。

### 3.5 AI（`src/integrations/ai`）
- 接口：`AiProvider`，含 5 个方法：
  - `generateCopy` 文案生成（EDM 标题/正文、SMS、WhatsApp、Push、社媒、广告）
  - `recommendSendTime` 发送时间推荐
  - `recommendSegment` 自动分群建议
  - `generateWorkflowDraft` Workflow 草案
  - `analyzeCampaign` 营销复盘与优化建议
- 已实现：`MockAiProvider`（返回结构化占位，前端可联调）。
- 留桩：`OpenAiProvider` / `AnthropicProvider` / `OllamaProvider`。建议统一用 JSON mode + zod 解析保证结构化输出（注释已写）。

### 3.6 Crawler（`src/integrations/crawler`）⚠️ 合规受限
- 接口：`CrawlerProvider { scrape(req): Promise<CrawlResult> }`，要求每条线索**必须带 `sourceUrl`**。
- 已实现：`MockCrawlerProvider`（返回样例，全部带 sourceUrl）。
- 留桩：`PlaywrightCrawlerProvider`（@playwright）。
- **合规开关**：`CRAWLER_ENABLED=false` 默认关闭，即便开启也只返回待审核线索；真实爬取必须在 `scrape()` 内保留来源、尊重 robots.txt、命中邮箱/电话的线索标记 `needsReview` 禁止自动导入。

---

## 4. 接入真实三方的标准步骤（以 SMS=Twilio 为例）

```bash
npm i twilio
```
编辑 `.env`：
```
SMS_PROVIDER=twilio
TWILIO_ACCOUNT_SID=xxx
TWILIO_AUTH_TOKEN=yyy
TWILIO_FROM_NUMBER=+1...
```
在 `src/integrations/sms/twilio.ts` 的 `send()` 中补：
```ts
const client = twilio(process.env.TWILIO_ACCOUNT_SID, process.env.TWILIO_AUTH_TOKEN);
const res = await client.messages.create({ to: msg.to, from: msg.from, body: msg.body });
return { provider: "twilio", messageId: res.sid, accepted: true };
```
无需改动任何 Service / API / 前端代码。

---

## 5. 本地零依赖运行

默认所有 `PROVIDER=mock`、`QUEUE_DRIVER=memory`、`AI_PROVIDER=mock`、`CRAWLER_ENABLED=false`。
此时**不需要 PostgreSQL 以外的任何外部服务**即可跑通：注册→建联系人→标签→分群→模板→Campaign→批量发送（mock 打印日志）→事件→Workflow→数据看板→AI 占位。

> 仅 `PostgreSQL` 是硬依赖（Prisma 需要）。本地可用 Docker 起一个 PG，或改用 SQLite 适配（需改 `schema.prisma` 的 datasource，不在本 MVP 范围）。
