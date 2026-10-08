#!/bin/sh
# NAS 上一键更新
set -e
cd "$(dirname "$0")"
docker compose pull
docker compose up -d
docker image prune -f
echo "OK — http://$(hostname -I 2>/dev/null | awk '{print $1}'):${WEB_PORT:-8080}"
