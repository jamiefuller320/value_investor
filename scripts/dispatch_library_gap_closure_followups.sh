#!/usr/bin/env bash
# Dispatch pinned intensive euro-ingest-loop runs from gap-closure follow-up JSON.
#
# Accepts the single-market evaluator shape (should_dispatch/pin_ticker/market_id)
# or the sprint/maintenance batch shape (dispatches[]).
#
# Usage: dispatch_library_gap_closure_followups.sh /tmp/gap_followup.json
set -euo pipefail

JSON_PATH="${1:-}"
if [ -z "$JSON_PATH" ] || [ ! -f "$JSON_PATH" ]; then
  echo "usage: $0 <gap_followup.json>" >&2
  exit 2
fi

require_safe() {
  local name="$1" val="$2" re="$3"
  if [ -n "$val" ] && ! [[ "$val" =~ $re ]]; then
    echo "Rejecting unsafe dispatch input: $name" >&2
    exit 1
  fi
}

mapfile -t ROWS < <(
  python3 - "$JSON_PATH" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
rows = data.get("dispatches")
if not isinstance(rows, list):
    rows = [data] if data.get("should_dispatch") else []
for row in rows:
    if not isinstance(row, dict) or not row.get("should_dispatch"):
        continue
    market = str(row.get("market_id") or "").strip()
    pin = str(row.get("pin_ticker") or "").strip()
    trigger = str(row.get("trigger") or "stall_slowdown").strip() or "stall_slowdown"
    print(f"{market}\t{pin}\t{trigger}")
PY
)

if [ "${#ROWS[@]}" -eq 0 ]; then
  echo "No library gap-closure follow-ups to dispatch"
  exit 0
fi

for row in "${ROWS[@]}"; do
  IFS=$'\t' read -r MARKET PIN_TICKER GAP_CLOSURE_TRIGGER <<<"$row"
  require_safe market "${MARKET:-}" '^[a-z][a-z0-9_]{0,63}$'
  require_safe pin_ticker "${PIN_TICKER:-}" '^[A-Za-z0-9][A-Za-z0-9._%-]{0,31}$'
  require_safe gap_closure_trigger "${GAP_CLOSURE_TRIGGER:-}" '^[a-z0-9_]{1,64}$'
  if [ -z "${MARKET:-}" ] || [ -z "${PIN_TICKER:-}" ]; then
    echo "Skipping incomplete follow-up row market=${MARKET:-} pin=${PIN_TICKER:-}" >&2
    continue
  fi
  if [ "${DRY_RUN:-}" = "1" ]; then
    echo "DRY_RUN euro-ingest-loop.yml market=$MARKET pin_ticker=$PIN_TICKER trigger=$GAP_CLOSURE_TRIGGER"
    continue
  fi
  gh workflow run euro-ingest-loop.yml \
    -f market="$MARKET" \
    -f max_targets=1 \
    -f max_bodies=40 \
    -f max_runtime_seconds=2100 \
    -f force=true \
    -f record_gap_closure=true \
    -f pin_ticker="$PIN_TICKER" \
    -f gap_closure_trigger="$GAP_CLOSURE_TRIGGER"
  echo "Dispatched euro-ingest-loop gap-closure follow-up for $MARKET $PIN_TICKER"
done
