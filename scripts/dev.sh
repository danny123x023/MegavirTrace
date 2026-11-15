#!/usr/bin/env bash
# Local development: database, API and web app.
#   scripts/dev.sh start|stop|status|restart-api
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/.run"
mkdir -p "$RUN"

db_start() {
  if ! docker ps --format '{{.Names}}' | grep -qx megavir-db; then
    if docker ps -a --format '{{.Names}}' | grep -qx megavir-db; then
      docker start megavir-db >/dev/null
    else
      docker run -d --name megavir-db -e POSTGRES_USER=megavir -e POSTGRES_PASSWORD=megavir -e POSTGRES_DB=megavir \
        -p 127.0.0.1:5433:5432 -v megavir-pg:/var/lib/postgresql/data --restart unless-stopped postgis/postgis:17-3.5 >/dev/null
    fi
  fi
  for _ in $(seq 1 30); do docker exec megavir-db pg_isready -U megavir >/dev/null 2>&1 && return 0; sleep 1; done
  echo "database did not become ready" >&2; return 1
}

start_bg() { # name, logfile, command...
  local name=$1 log=$2; shift 2
  if [[ -f "$RUN/$name.pid" ]] && kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null; then echo "$name already running"; return; fi
  setsid nohup "$@" >"$log" 2>&1 &
  echo $! >"$RUN/$name.pid"
  echo "$name started (log: $log)"
}

stop_bg() {
  local name=$1
  if [[ -f "$RUN/$name.pid" ]]; then
    local pid; pid=$(cat "$RUN/$name.pid")
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    rm -f "$RUN/$name.pid"
    echo "$name stopped"
  fi
}

api_start() { start_bg api "$RUN/api.log" "$ROOT/.venv/bin/uvicorn" megavir.api.main:app --host 127.0.0.1 --port 8000 --workers 2 --timeout-keep-alive 75; }
web_start() { (cd "$ROOT/web" && start_bg web "$RUN/web.log" npm run dev); }

case "${1:-}" in
  start) db_start; api_start; web_start; echo "open http://localhost:3000" ;;
  stop) stop_bg web; stop_bg api ;;
  restart-api) stop_bg api; sleep 1; api_start ;;
  status)
    curl -s -m 3 http://127.0.0.1:8000/health && echo || echo "api: down"
    curl -s -m 3 -o /dev/null -w "web: %{http_code}\n" http://localhost:3000/ || echo "web: down"
    ;;
  *) echo "usage: $0 start|stop|status|restart-api"; exit 1 ;;
esac
