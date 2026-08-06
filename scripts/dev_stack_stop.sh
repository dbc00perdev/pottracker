#!/usr/bin/env bash
# Stop everything ./scripts/dev_stack.sh started. Safe to run twice, from ANY
# shell — pollers are killed by their WINDOWS pid (read from the heartbeat
# files), because MSYS `kill`/pids don't reach processes started by a
# different MSYS session (e.g. a stack started from a Claude session).
set -u
cd "$(dirname "$0")/.."
RUN=run

# 1. Pollers: heartbeat carries the real Windows pid.
for hb in hb-ag hb-lg hb-vt hb-p56 hb-p57 hb-p60; do
  f="$RUN/$hb.json"
  if [ -f "$f" ]; then
    wpid=$(python -c "import json;print(json.load(open(r'$f'))['pid'])" 2>/dev/null | tr -d '\r')
    if [ -n "$wpid" ] && taskkill //F //PID "$wpid" >/dev/null 2>&1; then
      echo "  $hb poller: stopped (win pid $wpid)"
    else
      echo "  $hb poller: not running"
    fi
  fi
done

# 2. Same-shell fallback for anything this bash session started.
for name in poller-ag poller-lg poller-vt poller-p56 poller-p57 poller-p60 api web; do
  f="$RUN/$name.pid"
  [ -f "$f" ] && kill "$(cat "$f" | tr -d '\r')" 2>/dev/null
  rm -f "$f"
done

# 3. Belt: clear listeners on the stack's ports by Windows pid (catches
# orphaned uvicorn/vite workers). NB netstat output carries \r — strip it.
for port in 8002 5180; do
  for wpid in $(netstat -ano | grep ":$port" | grep -i listen | awk '{print $NF}' | tr -d '\r' | sort -u); do
    taskkill //F //T //PID "$wpid" >/dev/null 2>&1 && echo "  port $port: cleared (win pid $wpid)"
  done
done

echo "done. (machines untouched - pollers were read-only)"
