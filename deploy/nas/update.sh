#!/bin/sh
# 放在 /vol1/1000/Docker/huangguodl
set -e
cd "$(dirname "$0")"
docker compose pull
docker compose up -d
docker image prune -f
echo "OK — http://NAS_IP:8080"
