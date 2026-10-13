#!/usr/bin/env bash
# Long-running pending enrich with throughput-oriented defaults (see enrich_nocodb_view.py).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONUNBUFFERED=1

exec python3 -u scripts/enrich_nocodb_view.py \
  --table mewh1ynmcokfsfi \
  --view vw0q1gm39dsc3d9t \
  --only-pending \
  --wave-size "${WAVE_SIZE:-10}" \
  --chunk-size "${CHUNK_SIZE:-10}" \
  --resolve-concurrency "${RESOLVE_CONCURRENCY:-3}" \
  --harvest-concurrency "${HARVEST_CONCURRENCY:-4}" \
  --apify-timeout "${APIFY_ACTOR_TIMEOUT:-600}" \
  --company-timeout "${COMPANY_RESOLVE_TIMEOUT:-480}" \
  --resume \
  --state-file "${ENRICH_STATE_FILE:-/tmp/enrich-nocodb-pending-only.state.json}" \
  --checkpoint-file "${ENRICH_CHECKPOINT_FILE:-/tmp/enrich-nocodb-pending-checkpoint.json}" \
  "$@"
