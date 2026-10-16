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

run_once() {
  python3 -u scripts/enrich_nocodb_view.py \
    --table mewh1ynmcokfsfi \
    --view vw0q1gm39dsc3d9t \
    --only-pending \
    --wave-size "${WAVE_SIZE:-10}" \
    --chunk-size "${CHUNK_SIZE:-10}" \
    --resolve-concurrency "${RESOLVE_CONCURRENCY:-2}" \
    --harvest-concurrency "${HARVEST_CONCURRENCY:-2}" \
    --apify-timeout "${APIFY_ACTOR_TIMEOUT:-300}" \
    --company-timeout "${COMPANY_RESOLVE_TIMEOUT:-300}" \
    --resume \
    --state-file "$STATE_FILE" \
    --checkpoint-file "$CHECKPOINT_FILE" \
    "$@"
}

checkpoint_age_seconds() {
  python3 - "$CHECKPOINT_FILE" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    print(-1)
    raise SystemExit(0)
data = json.loads(path.read_text(encoding="utf-8"))
raw = data.get("updated_at") or data.get("finished_at")
if not raw:
    print(-1)
    raise SystemExit(0)
dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
print(int((datetime.now(timezone.utc) - dt).total_seconds()))
PY
}

if [[ "${ENRICH_WATCHDOG:-1}" == "0" ]]; then
  run_once "$@"
  exit $?
fi

while true; do
  echo "=== enrich pending $(date -u +%Y-%m-%dT%H:%M:%SZ) stall_limit=${STALL_SEC}s ===" >&2
  run_once &
  child=$!
  stall_killed=0
  while kill -0 "$child" 2>/dev/null; do
    sleep 120
    age="$(checkpoint_age_seconds || echo -1)"
    if [[ "$age" -ge 0 && "$age" -gt "$STALL_SEC" ]]; then
      echo "Checkpoint stale ${age}s (limit ${STALL_SEC}s); restarting enrich child." >&2
      kill "$child" 2>/dev/null || true
      wait "$child" 2>/dev/null || true
      stall_killed=1
      break
    fi
  done
  if [[ "$stall_killed" -eq 0 ]]; then
    wait "$child" || true
  fi
  # Brief pause before resume (same state file preserves processed_ids).
  sleep 5
done
