# 克隆即跑：CSTS Mautic（白标 + 简体中文）

本仓库 = **你的定制**（Next.js 运营台 + Mautic 白标/中文包 kit）。
Mautic 核心（第三方 GPL，约 1G）**不进仓库**，`setup.sh` 会在目标机按需拉取。

## 目标机前置
- PHP 8.1+（含 `php` 命令行）
- MySQL / MariaDB（提供 `mysql` 客户端更省事）
- `composer`（用于自动安装 Mautic 核心；没有则脚本会给出手动步骤）
- Node 18+（仅当你也要跑 Next.js 运营台）

## 三步跑起来

```bash
# 1) 克隆
git clone git@github.com:CenaCai/cms_marketing_auto.git
cd cms_marketing_auto

# 2) 准备配置（含数据库与管理员密码，不会被提交）
cp mautic-config.env.example mautic-config.env
#   编辑 mautic-config.env，填入目标机的 DB 凭据与 ADMIN_EMAIL/ADMIN_PASS

# 3) 一键搭建（拉核心 → 套白标 → 建库 → 初始化 → 清缓存）
bash setup.sh
```

跑完访问 `http://localhost:8080/s/login` 即为 **CSTS 白标 + 简体中文** 后台。
没填管理员凭据时，脚本会停在网页安装步骤——打开 `/installer.php` 装完后再 `bash setup.sh` 一次即可套白标。

## 只套白标（核心已装好）
```bash
bash mautic-csts-kit/apply.sh /path/to/existing/mautic
```

## 注意
- 脚本只复现「界面与语言」，**不含业务数据**；联系人/分群等需另走 Mautic 备份迁移。
- 覆盖的是 Mautic 核心文件，**升级 Mautic 后需重套** `mautic-csts-kit`（先 review `overrides/`）。
- 详情见 `mautic-csts-kit/README.md`。
