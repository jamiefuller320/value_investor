# Deferred-idea trigger check

Deferred ideas carry a free-text `revisit_when`. Free text cannot fire on its own, so
until now a met trigger was only noticed when someone happened to re-read the idea.
Two kinds of drift went unseen:

- **Met triggers.** For example, L556 was parked "until a fair book's epoch cost drag
  exceeds 1%" when `ai_judgment_fair` was already at 1.8%.
- **Triggers that can never fire.** These wait on a book that has since frozen
  (`still_in_buy_set`, `ai_judgment`). The 2026-10-06 assessment-model triage closed or
  retargeted 40+ of them by hand.

## Structured triggers

An idea may also carry a `trigger` that ops-monitor evaluates daily against committed
JSON. `revisit_when` stays the human-readable version.

```json
"trigger": {
  "any": [
    {"file": "docs/data/paper_automation/learning_tracks_review.json",
     "path": "reviews.ai_judgment_fair.metrics.epoch.cost_drag",
     "op": ">", "value": 0.01},
    {"on_or_after": "2026-12-01"}
  ]
}
```

| Field | Meaning |
|-------|---------|
| `all` / `any` | Exactly one, holding a non-empty list of conditions |
| `file` | Repo-relative committed JSON |
| `path` | Dotted keys. `key[field=value]` selects the first list row whose `field` equals `value` (e.g. `tracks[track_id=ai_judgment_fair].statistics.verdict`) |
| `op` | `>=` `>` `<=` `<` (numeric), `==` `!=`, `in` (list `value`), `exists`, `truthy` |
| `on_or_after` | `YYYY-MM-DD` date condition |

A missing file or path is **unknown**, never met. In `all` mode, any unmet condition
makes the whole trigger unmet.

Give an idea a structured trigger only when the condition is a committed number, flag
or date. Qualitative triggers ("a human picks option 2") stay free text.

```bash
ftse-defer add ... --trigger '{"all":[{"on_or_after":"2026-12-01"}]}'
ftse-defer set-trigger L556 --trigger '{"any":[...]}' [--revisit-when "new text"]
ftse-defer set-trigger L556 --clear
ftse-defer triggers            # evaluate now (read-only)
```

`deferred-review.md` marks these ideas _(machine-checked)_.

## Daily check

`check_deferred_triggers` runs at the end of ops-monitor's `collect_ops_findings`, after
the scoreboard and statistics stores are refreshed. It writes
`docs/data/deferred_trigger_check.json`, which ops-monitor commits. All findings are
`warn` and `auto_fixable=False`: nothing changes status automatically.

| Finding | When |
|---------|------|
| **Deferred idea triggers met** | An open or `now` idea's structured trigger is met. `first_met_at` is kept across runs |
| **Deferred idea triggers unreadable** | A trigger is invalid, or has stayed unknown (file or path missing) for more than 7 days (`unknown_since`). The grace period lets newly shipped stores land first |
| **Deferred idea triggers name frozen books** | An open idea's free-text `revisit_when` names a frozen book from `assessment_model.json` and the idea has not been edited since that book froze. Only ids containing `_` are matched; bare `rules` and `technical` are ordinary words |

## Clearing a finding

Each finding persists until the idea changes:

- **Pick it up:** `ftse-defer status <ID> now`, then do the work.
- **Retarget:** `ftse-defer set-trigger <ID> --trigger ... --revisit-when ...`.
- **Close:** `ftse-defer status <ID> done|drop --note "why"`.

For frozen-book mentions, edit `revisit_when` to name the primary or control. Any edit
after the freeze clears the mention.
