#!/usr/bin/env bash
#
# Mautic CSTS 白标 + 中文包 —— 一键复现脚本
#
# 作用：把本 kit 里的白标模板、logo、en_US 品牌文案、完整 zh_CN 中文包
#       应用到一台已安装好的 Mautic 7.x 上，并把默认语言设为简体中文。
#
# 用法：
#   bash apply.sh [MAUTIC_ROOT]
#     MAUTIC_ROOT  目标 Mautic 根目录（含 bin/console），默认 /Users/cenacai/mautic/app
#
# 安全说明：
#   - 本脚本【不会】触碰目标机的数据库密码等敏感配置；local.php 仅被合并
#      brand_name + locale 两个键，其余内容原样保留（先自动备份为 local.php.bak.csts）。
#   - 本 kit 不含任何密钥文件。
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OVERRIDES="$SCRIPT_DIR/overrides"
ROOT="${1:-/Users/cenacai/mautic/app}"

echo "▶ 目标 Mautic 根目录: $ROOT"

[ -d "$ROOT" ] || { echo "✗ 目录不存在: $ROOT" >&2; exit 1; }
[ -f "$ROOT/bin/console" ] || { echo "✗ 该目录未发现 bin/console，请确认是 Mautic 根目录" >&2; exit 1; }
[ -f "$ROOT/config/local.php" ] || { echo "✗ 未发现 config/local.php（Mautic 应已安装并配置）" >&2; exit 1; }

# 1) 复制所有覆盖文件（保持相对路径，与 Mautic 根目录结构一致）
echo "▶ 复制白标模板 / logo / en_US 品牌文案 / zh_CN 中文包 ..."
cp -R "$OVERRIDES/." "$ROOT/"

# 2) 合并 local.php：仅设置 brand_name + locale，保留其余配置（先备份）
echo "▶ 合并 config/local.php (brand_name=CSTS, locale=zh_CN) ..."
cp "$ROOT/config/local.php" "$ROOT/config/local.php.bak.csts"
php -r '
$root = $argv[1];
$file = $root."/config/local.php";
include $file;
if (!isset($parameters) || !is_array($parameters)) {
    fwrite(STDERR, "local.php 未定义 \$parameters 数组\n");
    exit(1);
}
$parameters["brand_name"]  = "CSTS";
$parameters["locale"]      = "zh_CN";
$parameters["sms_enabled"] = true;   // 开启短信 SMS 模块
$export = var_export($parameters, true);
file_put_contents($file, "<?php\n\n\$parameters = ".$export.";\n");
echo "  ✅ brand_name + locale + sms_enabled 已写入（备份: config/local.php.bak.csts）\n";
' "$ROOT"

# 2b) 发布 Twilio 短信集成，使营销活动(Campaign)里出现「发送短信」动作节点
#     （仅置 is_published=1；真实发送仍需在后台 Twilio 集成里填 SID/Token，或改用国内短信商插件）
echo "▶ 启用短信通道（发布 Twilio 集成，供 Campaign「发送短信」节点可选）..."
php -r '
$root = $argv[1];
include $root."/config/local.php";
$driver = $parameters["db_driver"] ?? "pdo_mysql";
if (strpos($driver, "mysql") === false) { echo "  ⚠ 非 MySQL 驱动，跳过（请到 后台→设置→插件→Twilio 手动启用）\n"; exit(0); }
$host   = $parameters["db_host"] ?? "localhost";
$port   = $parameters["db_port"] ?? 3306;
$name   = $parameters["db_name"] ?? "";
$user   = $parameters["db_user"] ?? "";
$pass   = $parameters["db_password"] ?? "";
$prefix = $parameters["db_table_prefix"] ?? "";
try {
    $pdo = new PDO("mysql:host=$host;port=$port;dbname=$name", $user, $pass);
    $tbl = $prefix."plugin_integration_settings";
    $st  = $pdo->prepare("UPDATE `".$tbl."` SET is_published=1 WHERE name=?");
    $st->execute(["Twilio"]);
    echo "  ✅ Twilio 集成已发布（Campaign 短信节点将出现；影响行数: ".$st->rowCount()."）\n";
} catch (Exception $e) {
    echo "  ⚠ 自动发布失败（".$e->getMessage()."），请到 后台→设置→插件→Twilio 手动启用\n";
}
' "$ROOT" || true

# 3) 清空生产缓存，使改动生效
echo "▶ 清空生产缓存（可能耗时十几秒）..."
php -d memory_limit=1024M "$ROOT/bin/console" cache:clear --env=prod

echo ""
echo "🎉 完成。访问后台 / 登录页应已是 CSTS 白标 + 简体中文界面；登录页已含「显示/隐藏密码」按钮，且输错密码不再锁定。"
echo "   短信 SMS 模块已开启：左侧「营销」组含「短信SMS」入口，Campaign 里可选「发送短信」节点。"
echo "   （如需真正发送短信，请到 后台→设置→插件→Twilio 填写凭证，或接入国内短信商自定义 transport。）"
echo "   若 Mautic 版本与 7.x 不一致，请先 review overrides/ 下被覆盖的 twig 与 en_US 文件。"
