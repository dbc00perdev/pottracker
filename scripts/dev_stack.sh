#!/usr/bin/env bash
# Start the full pottracker dev stack from Git Bash (like running the tracker):
#   3 FOCAS pollers (AG_1000 + LG_1000 mills, VT_23 lathe) + API :8002 + web :5180
#
#   $ ./scripts/dev_stack.sh
#
# Everything is READ-ONLY against the machines; the pollers write only to the
# dev DB mirror (localhost:5433). Logs land in ./run/logs/, PIDs in ./run/.
# Stop with ./scripts/dev_stack_stop.sh
#
# Lifetime: these processes belong to YOUR login session. They survive Claude
# sessions ending, but closing this Git Bash window may still take them down
# (Windows console job semantics). The permanent answer remains the Task
# Scheduler install (docs/runbooks/step0-poller-service.md).

set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)

DSN='postgresql+psycopg://pottracker_dev:dev_only_not_for_prod@localhost:5433/pottracker'
PY=.venv/Scripts/python
RUN=run
LOGS=$RUN/logs
mkdir -p "$LOGS"

start() { # name, cmd...
  local name=$1; shift
  if [ -f "$RUN/$name.pid" ] && kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null; then
    echo "  $name: already running (pid $(cat "$RUN/$name.pid"))"
    return
  fi
  nohup "$@" >"$LOGS/$name.log" 2>&1 &
  echo $! > "$RUN/$name.pid"
  echo "  $name: started (pid $!)  log: $LOGS/$name.log"
}

echo "starting pottracker dev stack (read-only against all machines)..."

start poller-ag "$PY" -m scripts.focas_service \
  --ip 10.1.10.58 --machine-id viper-ag-1000 \
  --machine-uuid 0390689a-0f25-4cb6-9924-a0b859944722 \
  --interval-seconds 60 --dsn "$DSN" \
  --heartbeat-path "$RUN/hb-ag.json" --lock-path "$RUN/ag.lock"

start poller-lg "$PY" -m scripts.focas_service \
  --ip 10.1.10.59 --machine-id viper-lg-1000 \
  --machine-uuid 005bcb5b-d45b-47b2-b36d-57fbaa9483c9 \
  --interval-seconds 60 --dsn "$DSN" \
  --heartbeat-path "$RUN/hb-lg.json" --lock-path "$RUN/lg.lock"

start poller-vt "$PY" -m scripts.focas_service \
  --ip 10.1.10.53 --machine-id viper-vt-23 --profile lathe \
  --machine-uuid 6844401d-017a-4093-9285-ed2fc3c58808 \
  --interval-seconds 60 --status-interval-seconds 10 --dsn "$DSN" \
  --heartbeat-path "$RUN/hb-vt.json" --lock-path "$RUN/vt.lock"

# Panther group (docs: tasks/spec-panther-onboarding.md) — read-only lathe
# profile, main path only. Soak started 2026-08-06 (gate 8).
start poller-p56 "$PY" -m scripts.focas_service \
  --ip 10.1.10.56 --machine-id panther-jake-2100ly --profile lathe \
  --machine-uuid 77d657a0-6f75-4a3d-867d-584c8589216a \
  --interval-seconds 60 --dsn "$DSN" \
  --heartbeat-path "$RUN/hb-p56.json" --lock-path "$RUN/p56.lock"

start poller-p57 "$PY" -m scripts.focas_service \
  --ip 10.1.10.57 --machine-id panther-jake-2100lys --profile lathe \
  --machine-uuid 5f263ff3-3a24-4d73-9652-e3955ee5253a \
  --interval-seconds 60 --dsn "$DSN" \
  --heartbeat-path "$RUN/hb-p57.json" --lock-path "$RUN/p57.lock"

start poller-p60 "$PY" -m scripts.focas_service \
  --ip 10.1.10.60 --machine-id panther-prod-2100lys-2 --profile lathe \
  --machine-uuid 9b406589-12ac-4829-a722-258a9a67a3cf \
  --interval-seconds 60 --dsn "$DSN" \
  --heartbeat-path "$RUN/hb-p60.json" --lock-path "$RUN/p60.lock"

DATABASE_URL="$DSN" start api "$PY" -m uvicorn apps.tooling.api.main:app \
  --host 127.0.0.1 --port 8002

( cd apps/tooling/web && TOOLING_API_PROXY=http://127.0.0.1:8002 \
    nohup bun run dev -- --port 5180 --strictPort \
    >"$ROOT/$LOGS/web.log" 2>&1 & echo $! > "$ROOT/$RUN/web.pid" )
echo "  web: started (pid $(cat "$RUN/web.pid"))  log: $LOGS/web.log"

echo ""
echo "app:    http://localhost:5180   (first poll cycles take ~40-60s)"
echo "health: curl -s http://127.0.0.1:8002/api/tooling/health"
echo "stop:   ./scripts/dev_stack_stop.sh"
