# Agent instructions — FTSE Value Investor

## Project objective

Ultimate goal: a **self-improving automated global value portfolio**.  
Interim goal: **high-quality prompts / decision packs** for manual verification and trade actions.

North-star stages and the “richness before breadth on the live path” rule are in [`docs/PROJECT_OBJECTIVE.md`](docs/PROJECT_OBJECTIVE.md). Keep the live screener on FTSE 350 until stage 4; grow other markets via `ftse-library` offline.

## Parked / later ideas (required)

When you give advice that is **not relevant now** or **potentially useful later** (deferred features, premature ideas, “revisit when…”, out-of-scope enhancements), **append it to the deferred-ideas store before ending the turn**:

```bash
ftse-defer add \
  --category later|not_now|security|both \
  --title "Short title" \
  --summary "One or two sentences" \
  --revisit-when "Concrete trigger for revisiting" \
  --section learning|universe|research|ops|not_now|security \
  --tags "comma,separated" \
  --source "https://cursor.com/agents/<bcId> or conversation topic"
```

Rules:

1. Call `ftse-defer add` for each distinct parked idea (the CLI dedupes by title).
2. Prefer `--category not_now` when explicitly advising against starting now; `--category later` for future enhancements.
3. Always regenerate is automatic on `add`; use `ftse-defer render` only if you edited `docs/deferred-ideas.json` by hand.
4. Do **not** hand-edit `docs/deferred-review.md` — it is generated from `docs/deferred-ideas.json`.
5. If several ideas appear in one answer, add each separately.

Human-readable review page: [`docs/deferred-review.md`](docs/deferred-review.md).
