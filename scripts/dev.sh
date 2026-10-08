#!/usr/bin/env bash
# hg-dl 一键起前后端：先清 8000/5173
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

kill_port() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti:"$port" | xargs -r kill -9 2>/dev/null || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" 2>/dev/null || true
  fi
}

echo "Stopping listeners on 8000 / 5173 ..."
kill_port 8000
kill_port 5173
sleep 1

cd "$ROOT/backend"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 \
  --reload-dir . --reload-dir ../packages/core &
BE_PID=$!

cd "$ROOT/frontend"
npm run dev -- --host 0.0.0.0 --port 5173 &
FE_PID=$!

trap 'kill $BE_PID $FE_PID 2>/dev/null || true' EXIT INT TERM
echo "Backend http://127.0.0.1:8000  Frontend http://127.0.0.1:5173 (pids $BE_PID $FE_PID)"
wait
