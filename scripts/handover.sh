#!/usr/bin/env bash
# FTSE Value Investor — operator handover briefing.
# Run from repo root: ./scripts/handover.sh
#
# Optional env:
#   HANDOVER_JSON=1  — emit machine-readable JSON (best-effort)
set -euo pipefail

REPO="${REPO:-jamiefuller320/value_investor}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

section() { printf '\n━━ %s ━━\n' "$1"; }
kv() { printf '  %-28s %s\n' "$1" "$2"; }
run_quiet() { "$@" >/dev/null 2>&1; }

git_branch="$(git branch --show-current 2>/dev/null || echo '?')"
git_main="$(git rev-parse --short origin/main 2>/dev/null || git rev-parse --short main 2>/dev/null || echo '?')"

section "Project"
kv "North star" "Self-improving global value portfolio (manual packs interim)"
kv "Current focus" "Stage 2b — AI-judgment paper book vs ^FTSE + rules control"
kv "Live universe" "FTSE 350 only until stage 4 (library grows offline)"
kv "Repo" "${REPO}"
kv "Branch" "${git_branch} @ main~${git_main}"

section "Stage snapshot (committed data)"
if [[ -f docs/data/project_progress.json ]]; then
  python3 - <<'PY'
import json
from pathlib import Path
p = json.loads(Path("docs/data/project_progress.json").read_text())
kv = lambda k, v: print(f"  {k:<28} {v}")
kv("Headline", (p.get("headline") or "")[:72] + "…" if len(p.get("headline") or "") > 72 else p.get("headline"))
kv("Screen run_at", (p.get("evidence") or {}).get("screen_run_at", "—")[:19])
kv("AI excess vs FTSE", (p.get("evidence") or {}).get("ai_excess_after_costs"))
kv("Rules excess", (p.get("evidence") or {}).get("rules_excess_after_costs"))
kv("Ingest stalled", (p.get("ingest_bottleneck") or {}).get("stalled"))
kv("zero_body_buy_tier", (p.get("evidence") or {}).get("zero_body_buy_tier"))
PY
else
  echo "  (docs/data/project_progress.json missing — run ftse-publish or Sunday screen)"
fi

section "Learning tracks (decision_review.json)"
python3 - <<'PY'
import json
from pathlib import Path
base = Path("docs/data/paper_automation")
for label, path in [
    ("AI judgment", base / "ai_judgment/decision_review.json"),
    ("Rules control", base / "decision_review.json"),
]:
    if not path.exists():
        print(f"  {label}: —")
        continue
    m = json.loads(path.read_text()).get("metrics") or {}
    excess = m.get("excess_after_costs")
    ret = m.get("total_return")
    print(f"  {label:<20} return={ret!s:>8}  excess_vs_FTSE={excess!s}")
PY

section "Ops monitor (docs/data/ops_status.json)"
if [[ -f docs/data/ops_status.json ]]; then
  python3 - <<'PY'
import json
from pathlib import Path
ops = json.loads(Path("docs/data/ops_status.json").read_text())
print(f"  overall: {ops.get('overall')}  run_at: {(ops.get('run_at') or '')[:19]}")
for f in ops.get("findings") or []:
    print(f"  [{f.get('severity')}] {f.get('title')}")
PY
else
  echo "  (no ops_status.json — run ftse-ops-monitor run)"
fi

section "Ingest health"
if command -v ftse-ingest-loop >/dev/null 2>&1; then
  ftse-ingest-loop status 2>/dev/null || true
else
  python3 -m value_investor.ingest_loop_cli status 2>/dev/null || true
fi
if [[ -f docs/data/ingest_health_log.json ]]; then
  python3 - <<'PY'
import json
from pathlib import Path
log = json.loads(Path("docs/data/ingest_health_log.json").read_text())
entries = log.get("entries") or []
if not entries:
    print("  (no ingest log entries)")
else:
    last = entries[-1]
    ha = last.get("health_after") or {}
    print(f"  last run: {(last.get('run_at') or '')[:19]}")
    print(f"  zero_body_buy_tier: {ha.get('zero_body_buy_tier')}  measured: {ha.get('measured_tickers')}")
    print(f"  delta_zero_body: {last.get('delta_zero_body')}  improved: {last.get('ingest_improved')}")
PY
fi

section "GitHub Actions (recent)"
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo "  Ingest loop:"
  gh run list --workflow=ingest-loop.yml --limit 2 --json status,conclusion,event,createdAt,displayTitle \
    2>/dev/null | python3 -c "
import json,sys
for r in json.load(sys.stdin):
    print(f\"    {r.get('createdAt','')[:16]}  {r.get('event'):18}  {r.get('status')}/{r.get('conclusion') or '—'}\")
" 2>/dev/null || echo "    (unable to list — check gh auth)"
  echo "  Open PRs:"
  gh pr list --state open --limit 5 2>/dev/null | sed 's/^/    /' || echo "    (none)"
else
  echo "  (gh not authenticated — skip)"
fi

section "External cron (cron-job.org)"
cat <<'EOF'
  Primary production triggers (see docs/ops/orchestrator-cron.md):
    orchestrator-sunday      Sun 06:20 UTC
    orchestrator-weekday     Mon–Fri 08:20 UTC
    ingest-loop              Mon/Wed/Fri 07:05 + 10:05 UTC  (jobId 8173801)
    analysis-review          Sun 10:35 UTC
    ops-monitor              Daily 07:45 UTC                 (jobId 8180483)
    data-backup              Sun 12:30 UTC                   (jobId 8179967)

  Re-import after PAT rotation:
    WORKFLOW_DISPATCH_PAT=… CRONJOB_API_KEY=… ./scripts/import_cron_jobs.py --all
EOF

section "Secrets & dispatch PAT"
cat <<'EOF'
  Cursor Cloud / local dispatch:
    WORKFLOW_DISPATCH_PAT  — preferred (fine-grained PAT, Actions: Read and write)
    GH_PAT                 — fallback (avoid ghs_… integration token in Cursor)

  Manual workflow dispatch:
    WORKFLOW=ingest-loop.yml INPUTS_JSON='{"force":"true","max_targets":"15"}' \
      ./scripts/dispatch_github_workflow.sh

  GitHub repo secrets (workflows): CURSOR_API_KEY, SMTP_*, EMAIL_TO, COMPANIES_HOUSE_API_KEY, …
EOF

section "Operator cheat sheet"
cat <<'EOF'
  Dashboard (published):     docs/index.html  (GitHub Pages)
  Project appraisal:         Overview tab → Project progress + Ingest health
  Paper sims (browser):      Paper funds tab — unrealized P/L on each strategy

  ftse-screen               Full FTSE 350 screen
  ftse-ingest-loop run      Local weekday ingest pass
  ftse-ops-monitor run      Health check + optional email
  ftse-data-backup snapshot Tier-1 tarball
  ftse-engineering list     Supervised engineering queue
  ftse-defer list           Parked / later ideas

  Docs:
    docs/ops/orchestrator-cron.md
    docs/ops/ops-monitor.md
    docs/ops/data-backup.md
    docs/PROJECT_OBJECTIVE.md
    AGENTS.md
EOF

section "Likely next actions"
cat <<'EOF'
  1. Merge PR #154 (WORKFLOW_DISPATCH_PAT) if still open; add secret to Cursor Cloud.
  2. Confirm ingest-loop run #30497287366 (force, max_targets=15) committed research artifacts.
  3. Sunday: orchestrator → screen refresh → ingest cap 15 → analysis-review → backup.
  4. Let stage 2b accumulate — avoid new tracks/knobs until AI excess vs FTSE turns positive.
  5. Watch zero_body_buy_tier after bootstrap — expect more measured tickers, then body fetch depth.
EOF

printf '\nHandover complete (%s UTC).\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
