#!/usr/bin/env bash
# Long-running pending enrich with throughput-oriented defaults (see enrich_nocodb_view.py).
# Restarts automatically on exit; kills the child if checkpoint is stale (ENRICH_STALL_SEC).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONUNBUFFERED=1

STATE_FILE="${ENRICH_STATE_FILE:-/tmp/enrich-nocodb-pending-only.state.json}"
CHECKPOINT_FILE="${ENRICH_CHECKPOINT_FILE:-/tmp/enrich-nocodb-pending-checkpoint.json}"
STALL_SEC="${ENRICH_STALL_SEC:-5400}"

ENRICH_CMD=(
  python3 -u scripts/enrich_nocodb_view.py
  --table mewh1ynmcokfsfi
  --view vw0q1gm39dsc3d9t
  --only-pending
  --wave-size "${WAVE_SIZE:-10}"
  --chunk-size "${CHUNK_SIZE:-10}"
  --resolve-concurrency "${RESOLVE_CONCURRENCY:-2}"
  --harvest-concurrency "${HARVEST_CONCURRENCY:-2}"
  --apify-timeout "${APIFY_ACTOR_TIMEOUT:-300}"
  --company-timeout "${COMPANY_RESOLVE_TIMEOUT:-300}"
  --resume
  --state-file "$STATE_FILE"
  --checkpoint-file "$CHECKPOINT_FILE"
)

run_once() {
  "${ENRICH_CMD[@]}" "$@"
}

checkpoint_updated_at() {
  python3 - "$CHECKPOINT_FILE" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    print("")
    raise SystemExit(0)
data = json.loads(path.read_text(encoding="utf-8"))
print(data.get("updated_at") or data.get("finished_at") or "")
PY
}

if [[ "${ENRICH_WATCHDOG:-1}" == "0" ]]; then
  run_once "$@"
  exit $?
fi

stop_child() {
  local pid=$1
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  local waited=0
  while kill -0 "$pid" 2>/dev/null && [[ "$waited" -lt 30 ]]; do
    sleep 1
    waited=$((waited + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  wait "$pid" 2>/dev/null || true
}

while true; do
  echo "=== enrich pending $(date -u +%Y-%m-%dT%H:%M:%SZ) stall_limit=${STALL_SEC}s ===" >&2
  "${ENRICH_CMD[@]}" "$@" &
  child=$!
  stall_killed=0
  last_ckpt="$(checkpoint_updated_at)"
  progress_at=$(date +%s)
  while kill -0 "$child" 2>/dev/null; do
    sleep 120
    current_ckpt="$(checkpoint_updated_at)"
    now=$(date +%s)
    if [[ -n "$current_ckpt" && "$current_ckpt" != "$last_ckpt" ]]; then
      last_ckpt="$current_ckpt"
      progress_at=$now
    fi
    idle=$((now - progress_at))
    if [[ "$idle" -gt "$STALL_SEC" ]]; then
      echo "No checkpoint progress for ${idle}s (limit ${STALL_SEC}s); restarting enrich child." >&2
      stop_child "$child"
      stall_killed=1
      break
    fi
  done
  if [[ "$stall_killed" -eq 0 ]]; then
    wait "$child" || true
  fi
  sleep 5
done
