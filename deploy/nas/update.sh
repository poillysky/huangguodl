#!/bin/sh
# NAS 上一键更新 — 建议放在 /vol1/1000/Docker/huangguodl
set -e
cd "$(dirname "$0")"
docker compose pull
docker compose up -d
docker image prune -f
echo "OK — open http://NAS_IP:${WEB_PORT:-8080}"
