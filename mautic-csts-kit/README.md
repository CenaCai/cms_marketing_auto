# Mautic CSTS 白标 + 中文包 —— 一键复现 Kit

把一台已定制好的 Mautic（CSTS 白标 + 简体中文界面）完整复现到另一台机器。

## 包含什么

| 类别 | 数量 | 说明 |
|------|------|------|
| 白标模板 (twig) | 8 | 侧边栏导航(csts-nav/cstsLabels/ri- 图标)、品牌色(#csts-brand→#2563eb)、登录/异常/列表页标题 |
| 自定义 logo | 3 | `logo--csts.png`（app/assets、CoreBundle/Assets、media/images 三处） |
| en_US 品牌文案 | 23 | 核心翻译源中 "Mautic"→"CSTS" 的替换（英文回退时也显示 CSTS） |
| zh_CN 中文包 | 43 bundle | 完整定制中文包（含垃圾键清理、默认中文） |
| local.php 片段 | — | 合并 `brand_name=CSTS` + `locale=zh_CN` + `sms_enabled=true` 三个键 |
| 登录优化覆盖 | 2 | `app/config/security.php`（关闭输错锁定 `login_throttling=false`）+ `UserBundle/.../Security/login.html.twig`（密码框显示/隐藏明文切换按钮） |
| 短信 SMS 模块 | — | 侧边栏「营销」组新增「短信SMS」(`/s/sms`) 入口；`apply.sh` 自动发布 Twilio 集成，使 Campaign 出现「发送短信」可选节点 |

> `ri-` 图标字体来自 Mautic 7 核心自带的 Remix Icon 库，**无需额外打包**。

> **登录体验优化**：套用本 kit 后，登录页密码框带「显示/隐藏明文」切换按钮，且 Symfony 默认的输入错误锁定已关闭（输错密码不再锁定 30 分钟）。这两项通过 `overrides/` 中的 `security.php` 与 `login.html.twig` 覆盖实现，随 `apply.sh` 自动生效。

> **短信 SMS 模块**：`apply.sh` 会写入 `sms_enabled=true` 并发布 Twilio 集成，套用后左侧「营销」组出现「短信SMS」入口，营销活动(Campaign)里可选「发送短信」动作节点。**真正发送短信仍需凭证**——到 后台→设置→插件→Twilio 填 SID/Token，或按 `TransportInterface` 写一个国内短信商（阿里云/腾讯云）自定义 transport 插件。

## 前置条件

- 目标机器已安装 **Mautic 7.x**（版本尽量与本机一致；twig / en_US 覆盖文件是版本相关的）。
- PHP 命令行可用（`php` 在 PATH 中）。
- 目标机已有自己的 `config/local.php`（含数据库等配置）。

## 用法

```bash
# 默认目标 /Users/cenacai/mautic/app
bash apply.sh

# 或指定其它 Mautic 根目录
bash apply.sh /var/www/mautic
```

脚本会：
1. 把 `overrides/` 下所有文件按相对路径复制到 Mautic 根（与现有文件合并/覆盖）。
2. 备份 `config/local.php` → `config/local.php.bak.csts`，并**仅**写入 `brand_name` + `locale` 两个键（保留 DB 密码等一切原有配置）。
3. 执行 `cache:clear --env=prod` 使改动生效。

## 重要注意事项

- **覆盖核心文件**：本 kit 会覆盖目标的 `en_US` / `zh_CN` 翻译与部分核心视图。这是白标化的固有行为——**Mautic 升级后需重新套用本 kit**（先 `git diff` 或备份对比，review 有无冲突）。
- **不迁数据**：本 kit 只复现「界面与语言」，不含数据库。另一台机器的联系人/分群/邮件等数据需通过 Mautic 自带备份/迁移或数据库 dump 单独处理。
- **不含密钥**：kit 内无任何密钥；`local.php` 的数据库密码等由目标机自身提供。
- **版本差异**：若目标 Mautic 版本与本机不同，应用前请先 review `overrides/` 中被覆盖的 twig 与 en_US 文件，避免模板结构冲突。

## 目录结构

```
mautic-csts-kit/
├── apply.sh              # 一键复现脚本
├── README.md
└── overrides/            # 所有定制文件，相对路径 = Mautic 根目录
    ├── app/bundles/.../views/.../*.twig
    ├── app/bundles/.../Translations/en_US/*.ini
    ├── app/assets/images/logo--csts.png
    ├── media/images/logo--csts.png
    └── translations/zh_CN/<Bundle>/messages.ini
```
