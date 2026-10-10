#!/bin/sh
set -e

# 让 cockpit 指向 compose 网络内的 mautic 服务
# 容器内 127.0.0.1 是 cockpit 自己，不是 Mautic；改成 compose 服务名 mautic:80
# 改写只作用于容器内的 config.json 副本，不修改你本机的文件
if [ -f config.json ]; then
  sed -i 's#"base_url": "http://127.0.0.1:8080"#"base_url": "http://mautic:80"#' config.json
fi

exec python3 cockpit.py --port 8090 --host 0.0.0.0
