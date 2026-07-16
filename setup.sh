#!/usr/bin/env bash
#
# Mautic CSTS —— 克隆即跑 一键搭建脚本
#
# 作用：从本仓库（仅含你的定制：白标 + 中文包）出发，在目标机自动
#       1) 拉取/识别 Mautic 7.x 核心（第三方 GPL，不在你仓库里）
#       2) 套用白标 + 简体中文定制
#       3) 建库 + 初始化管理员（如提供 env 配置）
#       4) 清缓存，直接可访问
#
# 用法：
#   bash setup.sh                 # 使用 ./mautic 作为核心目录，读取同目录 mautic-config.env
#   bash setup.sh /var/www/mautic # 指定核心目录
#
# 前置：php / composer（或 git+composer）/ mysql 客户端 在 PATH 中。
# 配置：在同目录创建 mautic-config.env（参考 mautic-config.env.example）。
#       不提供 env 时，脚本只装核心 + 套白标，DB/管理员需走 Mautic 网页安装。
#
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_DIR="$REPO_DIR/mautic-csts-kit"
APPLY_SH="$KIT_DIR/apply.sh"

# ---- 可配置项（环境变量优先，其次 mautic-config.env，再次默认） ----
MAUTIC_VERSION="${MAUTIC_VERSION:-7.1.*}"
ROOT="${1:-${MAUTIC_ROOT:-$REPO_DIR/mautic}}"

# 加载同目录 env（若存在）
if [ -f "$REPO_DIR/mautic-config.env" ]; then
  set -a; source "$REPO_DIR/mautic-config.env"; set +a
fi

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_NAME="${DB_NAME:-mautic}"
DB_USER="${DB_USER:-mautic}"
DB_PASS="${DB_PASS:-mautic_pass_change_me}"
SITE_URL="${SITE_URL:-http://localhost:8080}"
ADMIN_EMAIL="${ADMIN_EMAIL:-}"
ADMIN_PASS="${ADMIN_PASS:-}"

log()  { echo -e "\033[36m▶\033[0m $*"; }
ok()   { echo -e "\033[32m✅\033[0m $*"; }
warn() { echo -e "\033[33m⚠️\033[0m $*"; }
err()  { echo -e "\033[31m✗\033[0m $*" >&2; }

# ---- 0) 前置检查 ----
[ -f "$APPLY_SH" ] || { err "未找到 $APPLY_SH"; exit 1; }
command -v php >/dev/null 2>&1 || { err "需要 php 命令行，请先安装 PHP 8.1+"; exit 1; }

# ---- 1) 安装 Mautic 核心（若 ROOT 无 bin/console） ----
if [ ! -f "$ROOT/bin/console" ]; then
  log "未检测到 Mautic 核心，准备安装 $MAUTIC_VERSION 到 $ROOT"
  mkdir -p "$ROOT"

  if command -v composer >/dev/null 2>&1; then
    log "使用 composer 安装 Mautic $MAUTIC_VERSION 核心 ..."
    if composer create-project "mautic/recommended-project:$MAUTIC_VERSION" "$ROOT" --no-interaction \
       && [ -f "$ROOT/bin/console" ]; then
      ok "核心已通过 composer 安装"
    elif command -v git >/dev/null 2>&1; then
      log "create-project 失败，改从官方仓库克隆源码 + composer install ..."
      rm -rf "$ROOT"; mkdir -p "$ROOT"
      git clone --depth 1 --branch "${MAUTIC_VERSION/.*/}.x" https://github.com/mautic/mautic.git "$ROOT" \
        && (cd "$ROOT" && composer install --no-interaction) \
        && [ -f "$ROOT/bin/console" ] \
        && ok "核心已通过 git 安装" \
        || { err "git/composer 安装失败，请手动安装后重跑"; exit 1; }
    else
      err "composer 与 git 均不可用，无法自动安装核心。"; exit 1
    fi
  else
    err "缺少 composer，无法自动安装 Mautic 核心。"
    echo "   请先安装 composer（https://getcomposer.org），或手动安装 Mautic $MAUTIC_VERSION 到 $ROOT 后重跑：bash setup.sh $ROOT"
    exit 1
  fi
else
  ok "已检测到 Mautic 核心：$ROOT"
fi

[ -f "$ROOT/bin/console" ] || { err "$ROOT/bin/console 仍不存在"; exit 1; }

# ---- 2) 建库（若提供 DB 凭据且 mysql 客户端可用） ----
if [ -n "$DB_PASS" ] && command -v mysql >/dev/null 2>&1; then
  log "确保数据库 '$DB_NAME' 存在 ..."
  mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASS" \
    -e "CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" \
    && ok "数据库就绪" \
    || warn "建库失败（可能已存在或凭据错误），继续执行"
fi

# ---- 3) 初始化 Mautic（仅当 local.php 尚不存在，且提供了管理员凭据） ----
if [ ! -f "$ROOT/config/local.php" ]; then
  if [ -n "$ADMIN_EMAIL" ] && [ -n "$ADMIN_PASS" ]; then
    log "运行 mautic:install 初始化（建表 + 管理员）..."
    php -d memory_limit=1024M "$ROOT/bin/console" mautic:install \
      --db_driver=pdo_mysql \
      --db_host="$DB_HOST" --db_port="$DB_PORT" \
      --db_name="$DB_NAME" --db_user="$DB_USER" --db_password="$DB_PASS" \
      --admin_email="$ADMIN_EMAIL" --admin_password="$ADMIN_PASS" \
      --admin_firstname=CSTS --admin_lastname=Admin \
      --site_url="$SITE_URL" --no-interaction \
      && ok "Mautic 已初始化" \
      || { err "mautic:install 失败，请检查 DB 凭据与端口"; exit 1; }
  else
    warn "未提供 ADMIN_EMAIL/ADMIN_PASS，跳过自动安装。"
    echo "   请通过网页安装完成初始化：浏览器打开 $SITE_URL/installer.php"
    echo "   安装完成后，再次运行：bash setup.sh $ROOT  （将套用白标 + 中文）"
  fi
else
  ok "local.php 已存在，跳过 mautic:install"
fi

# ---- 4) 套用白标 + 中文包（含 local.php 合并与清缓存） ----
if [ -f "$ROOT/config/local.php" ]; then
  log "套用 CSTS 白标 + 简体中文定制 ..."
  bash "$APPLY_SH" "$ROOT"
else
  warn "尚未初始化（无 local.php），跳过白标套用。"
  echo "   请打开 $SITE_URL/installer.php 完成安装，然后重跑：bash setup.sh $ROOT"
fi

# ---- 5) 收尾 ----
echo ""
if [ -f "$ROOT/config/local.php" ]; then
  ok "完成！访问后台：$SITE_URL/s/login （白标 CSTS + 简体中文）"
else
  warn "尚未完成 Mautic 初始化。请打开 $SITE_URL/installer.php 安装，"
  echo "   安装后再运行：bash setup.sh $ROOT"
fi
echo "   提示：本脚本只复现「界面与语言」，不含业务数据；"
echo "         Mautic 升级后需重新套用 mautic-csts-kit（见其 README）。"
