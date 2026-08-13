#!/usr/bin/env bash
# Run memo backfill batches until no buy-tier names lack published memos.
set -euo pipefail
cd "$(dirname "$0")/.."

BATCH_SIZE="${BATCH_SIZE:-6}"
LOG_DIR="output/memo_backfill_runs"
mkdir -p "$LOG_DIR"

commit_batch() {
  local batch_num="$1"
  git add \
    docs/data/memo_backfill_state.json \
    docs/data/latest.json \
    docs/research/*.md \
    docs/data/research/
  if git diff --cached --quiet; then
    echo "No changes to commit for batch $batch_num"
    return 0
  fi
  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git pull --rebase --autostash origin main
  local created
  created=$(python3 -c "import json; print(','.join(json.load(open('docs/data/memo_backfill_state.json')).get('created',[])))")
  git commit -m "chore: memo backfill batch ${batch_num} — ${created} [skip ci]"
  git push origin main
}

missing_count() {
  ftse-research-backfill --status 2>/dev/null | awk '/Missing memos:/{print $3}'
}

batch_num=2
while true; do
  missing="$(missing_count)"
  echo "=== $(date -Is) missing_memos=${missing} ==="
  if [[ "${missing}" == "0" ]]; then
    echo "All buy-tier memos complete."
    break
  fi
  log="$LOG_DIR/batch_${batch_num}.log"
  echo "Starting batch $batch_num (size=$BATCH_SIZE) -> $log"
  if ! ftse-research-backfill --batch-size "$BATCH_SIZE" -v 2>&1 | tee "$log"; then
    echo "Backfill batch $batch_num had errors; see $log"
  fi
  commit_batch "$batch_num"
  batch_num=$((batch_num + 1))
  sleep 2
done

ftse-research-backfill --status
