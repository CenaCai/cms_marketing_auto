# cms_marketing_auto —— Mautic CSTS 白标 + 简体中文定制仓库

> **本仓库的主交付物是 Mautic CSTS Kit**：一套套在 [Mautic 7.x](https://github.com/mautic/mautic) 开源核心之上的**白标（CSTS）+ 简体中文**定制包。
> 实际部署时，Mautic 核心由 `setup.sh` 自动拉取（第三方 GPL，不入库），本仓库只承载你的定制。

---

## 仓库结构（一眼看清）

```
cms_marketing_auto/
├── mautic-csts-kit/        # ★ 主交付物：白标 + 中文包 kit（twig / logo / en_US / zh_CN / 登录优化）
│   ├── apply.sh            #   一键把 overrides/ 套用到一台 Mautic 核心
│   └── README.md           #   kit 详细说明（含什么、怎么用、注意事项）
├── setup.sh                # 克隆即跑：拉 Mautic 核心 → 套白标 → 建库 → 清缓存
├── QUICKSTART.md           # 本地/生产 快速开始（Mautic CSTS）
├── mautic-config.env.example  # setup.sh 用的数据库/管理员配置样例
└── legacy/
    └── nextjs-ops-console/ # ⚠️ 早期 MVP 脚手架（Next.js 14 运营台），已不再是主交付物，仅供归档参考
```

---

## 快速开始（Mautic CSTS）

```bash
# 1. 准备配置（数据库 / 管理员），参考样例
cp mautic-config.env.example mautic-config.env
#   按需修改 DB_HOST / DB_USER / DB_PASS / ADMIN_EMAIL / ADMIN_PASS

# 2. 一键克隆即跑（自动拉 Mautic 7.x 核心 + 套白标 + 建库 + 清缓存）
bash setup.sh
#   完成后访问后台：http://localhost:8080/s/login （白标 CSTS + 简体中文）
```

更细的步骤、包含清单、注意事项见 **`mautic-csts-kit/README.md`** 与 **`QUICKSTART.md`**。

### 登录信息
- 路径：`/s/login`
- 管理员账号：`admin` / `Maut1cR0cks!`（由 config/local.php 或 setup.sh 的 ADMIN_PASS 决定）
- 登录页密码框带「显示/隐藏明文」切换按钮；输错密码不再锁定（Symfony 默认节流已关闭）

---

## ⚠️ 关于 `legacy/nextjs-ops-console/`

该目录是项目早期基于 **Next.js 14** 自建的 CRM / 营销自动化运营台 MVP 脚手架（联系人中心、标签分群、EDM/SMS、Workflow、AI 运营等），**现已不是本仓库的主交付物**。整体项目已转向基于 Mautic 开源框架定制，运营台相关能力由 Mautic CSTS 承接。

保留此处仅作历史参考与能力对照，不再随主流程维护。若需本地运行该遗留工程：

```bash
cd legacy/nextjs-ops-console
npm install
cp .env.example .env      # 默认已为 SQLite + mock，零外部依赖
npx prisma generate && npm run prisma:dbpush && npm run db:seed
npm run dev               # http://localhost:3000
```
