#!/usr/bin/env bash
# Stop everything ./scripts/dev_stack.sh started. Safe to run twice.
set -u
cd "$(dirname "$0")/.."
RUN=run

for name in poller-ag poller-lg poller-vt api web; do
  f="$RUN/$name.pid"
  if [ -f "$f" ]; then
    pid=$(cat "$f")
    if kill -0 "$pid" 2>/dev/null; then
      # taskkill /T takes the child tree (uvicorn/vite workers) too
      taskkill //F //T //PID "$pid" >/dev/null 2>&1 && echo "  $name: stopped (pid $pid)" \
        || echo "  $name: kill failed (pid $pid)"
    else
      echo "  $name: not running"
    fi
    rm -f "$f"
  else
    echo "  $name: no pid file"
  fi
done
echo "done. (machines untouched - pollers were read-only)"
