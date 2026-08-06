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

# FLEET LAUNCHER (docs/10 §8.2, cutover 2026-08-06): ONE process polls every
# enabled machine from the registry — adding a machine needs NO edit here,
# just its shared.machine row + enabled=true after the docs/10 §7 gates.
# --also keeps not-yet-enabled machines polling for their gate-8 soaks
# (currently the three Panthers); remove each --also when it's enabled.
start fleet "$PY" -m scripts.focas_fleet --dsn "$DSN" \
  --also 77d657a0-6f75-4a3d-867d-584c8589216a \
  --also 5f263ff3-3a24-4d73-9652-e3955ee5253a \
  --also 9b406589-12ac-4829-a722-258a9a67a3cf

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
