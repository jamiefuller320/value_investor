#!/usr/bin/env bash
# Re-memo buy-tier legacy markdown memos until all have canonical research.json.
set -euo pipefail
cd "$(dirname "$0")/.."

BATCH_SIZE="${BATCH_SIZE:-6}"
LOG_DIR="output/legacy_rememo_runs"
mkdir -p "$LOG_DIR"

commit_batch() {
  local batch_num="$1"
  git add \
    docs/data/legacy_rememo_state.json \
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
  created=$(python3 -c "import json; print(','.join(json.load(open('docs/data/legacy_rememo_state.json')).get('rememoed',[])))")
  git commit -m "chore: legacy re-memo batch ${batch_num} — ${created} [skip ci]"
  git push origin main
}

legacy_count() {
  ftse-research-backfill --rememo-legacy --status 2>/dev/null | awk '/Legacy re-memo needed:/{print $4}'
}

batch_num=1
while true; do
  legacy="$(legacy_count)"
  echo "=== $(date -Is) legacy_rememo=${legacy} ==="
  if [[ "${legacy}" == "0" ]]; then
    echo "All legacy memos have canonical JSON — rebuilding full index."
    python3 -c "
from pathlib import Path
from value_investor.research.memo_backfill import rebuild_full_research_index
print(rebuild_full_research_index(Path('output')))
"
    git add docs/data/latest.json docs/data/research docs/research
    git commit -m "chore: rebuild research index after legacy re-memo [skip ci]" || true
    git push origin main || true
    break
  fi
  log="$LOG_DIR/batch_${batch_num}.log"
  ftse-research-backfill --rememo-legacy --batch-size "$BATCH_SIZE" -v 2>&1 | tee "$log"
  commit_batch "$batch_num"
  batch_num=$((batch_num + 1))
  sleep 2
done

ftse-research-backfill --rememo-legacy --status
