# Parked & later ideas — periodic review

Auto-generated from [`docs/deferred-ideas.json`](deferred-ideas.json) (updated `2026-07-22T10:03:02+00:00`).

Agents append new parked ideas with `ftse-defer add …` (see `AGENTS.md`). Do not hand-edit this markdown; edit the JSON store or use the CLI, then `ftse-defer render`.

**How to use:** Review quarterly (or after ~8–12 weekly archives). Move items to done/drop/now via `ftse-defer status`.

---

## Sessions mined

| Agent | URL | Focus |
|-------|-----|--------|
| Stock open dashboard behavior | https://cursor.com/agents/bc-957a7c96-f14d-494a-83f8-5f2a618a3446 | Paper funds, automation, self-learning, universe |
| Ftse key verification models | https://cursor.com/agents/bc-84f8eb22-819f-4ea2-b70d-18ab2f010668 | Full-run proof, CI, data sources, research limits |
| Ftse verify key models | https://cursor.com/agents/bc-f66d83fe-cfe6-44a6-b3de-51c10d6ae515 | Env/gitignore, secrets hygiene |
| Ftse key verification | https://cursor.com/agents/bc-9bff5dd3-473b-4cf0-9374-3bc91363ec15 | ftse-verify-key (little deferred) |
| Merge request commit failure | https://cursor.com/agents/bc-8c2f37c7-9320-4eeb-bd4d-297612b773a5 | Models roadmap, research overlay, data gaps |

---

## Not relevant now (do not start yet)

| # | Idea | Summary | Revisit when |
|---|------|---------|--------------|
| N1 | **Widen universe first (AIM / Europe / worldwide)** | Learning bottleneck is weekly periods, not name count; worse data/liquidity; no code path | FTSE 350 decision-review loop is stable and there is a clear data story |
| N2 | **Evolutionary / survival-of-the-fittest parallel sims** | Sparse weekly history leads to overfitting; high-churn genomes look fit until costs dominate | Many tens of weekly snapshots + cost-penalised walk-forward fitness |
| N3 | **Rewrite assign_signal() from LLM research** | Research should overlay, not own the primary quant signal | Explicit product decision to make LLM output part of base signal |
| N4 | **More cheapness / P/E-variant screens** | Saturated; adds noise | Per-model attribution shows a cheapness gap |
| N5 | **DCF as a screen model** | yfinance too thin across FTSE | Better fundamentals (RNS/paid API) |
| N6 | **ESG / sentiment as quant models** | Belongs in research unless a dedicated feed exists | Paid ESG/sentiment source available |
| N7 | **Level 2 / ADVFN order book** | Weak fit for weekly batch without licensed depth | Licensed L2 + trade-plan overlay needed |
| N8 | **Resource/reserve miner metrics** | Sector-specific, hard data | Dedicated resources feed |
| N9 | **Extra storage compression / same-day cron micro-tests** | Explicitly skipped after earlier storage/cron work | Local output/history/ pain returns |
| N10 | **Node 20 Actions deprecation nit** | Harmless noise | Forced by action upgrades |
| N11 | **Sync private live holdings into git/CI** | Privacy; dashboard localStorage must stay private | Private bridge (not git) is designed |
| N12 | **Browser-only fully independent automation** | Only runs when dashboard is open | Server Action/ftse-paper-auto insufficient |
| N13 | **Capital at risk / live broker automation (stage 6)** | Do not connect live capital or broker APIs until stages 2–5 are proven in paper with cost-aware review. | Manual packs trusted, decision-review learning working, and multi-market paper track proven |
| N14 | **Live Trading 212 API integration** | Do not wire live order placement yet. T212 API is beta (non-idempotent orders); project is still at stage 2 manual packs. Prefer demo/paper path first when broker work starts. | Stages 2–5 exit criteria met and human override workflow defined (see N13) |
| N15 | **Expand ladder before T212 catalogue verification** | Do not grow new offline markets from allowlist assumptions alone; hang_seng/sti/asx200 look 100% on suffix heuristics but need catalogue hit rates before further APAC breadth. | Catalogue fetched and alignment_report.json shows per-market catalogue_hit_pct |
| N16 | **Do not chase live Cursor usage API before envelope calibration** | Live usage API (L32) is blocked on Cursor exposing credits to CURSOR_API_KEY. Prefer running the £30/week estimated gate for a few cycles and recalibrating estimated_memo_usd (L52) before investing in billing integration. | Cursor documents a usage/credits API for CURSOR_API_KEY, or estimated vs billed spend diverges badly after 2–4 constrained weeks |
| N17 | **Do not expand live screen beyond FTSE 350 yet** | Library breadth is far ahead (16 graduated markets). Stage 4 live expansion should wait until stage-2 decision packs are routinely trusted and decision-review has enough marks to adjust knobs. | Stage 2 exit criteria met and decision-review has actionable excess-return history |
| N18 | **Do not let AI judgment own live capital path yet** | Primary learning track is paper-only. Keep live broker automation and any promotion of AI gates to real capital off until the AI-judgment book shows persistent excess vs ^FTSE and vs the rules control in walk-forward review. | AI judgment paper track shows persistent excess vs screen-only and FTSE in walk-forward review |
| N19 | **Do not backdate research revisions for past paper decisions** | Extending source lookbacks and re-running memos is fine going forward, but inventing historical revisions as-of past run dates would leak post-period knowledge into AI-judgment / historical_analysis PIT overlays. | Never as a learning shortcut; only reconsider if building a separate counterfactual research lab outside the live paper track |
| N20 | **Companies House Streaming API for realtime filings** | Streaming API pushes company/filing changes over long-lived connections; our research path only needs on-demand REST GET for search, filing-history, and document download. Keys are not interchangeable with REST. | Need near-realtime UK filing alerts outside weekly research cycles |

---

## Potentially useful later

### Learning & simulation

| # | Idea | Summary | Revisit when |
|---|------|---------|--------------|
| L2 | **Evolutionary genomes (stage 2)** | Genomes = sim knobs ± weight deltas; fitness = excess − λ×costs; elites + small mutations; freeze screen signals first | After L1; history thick enough to trust fitness |
| L4 | **Clarify tactical vs whole-position stops** | Semantics ambiguous if/when sim consumes plans | L3 starts |
| L6 | **Sector-stratified backtest** | Does cheapness work by sector? | Enough archived runs |

### Universe & data

| # | Idea | Summary | Revisit when |
|---|------|---------|--------------|
| L8 | **Official AIC / published NAV for trusts** | Trust track uses book-value NAV proxy | Discount-to-book too coarse |
| L11 | **UK-primary fundamentals (Refinitiv/FMP/RNS depth)** | Supplement yfinance balance-sheet/dividend gaps | Data-quality errors dominate signals |
| L12 | **Paid news API** | Beyond Google News RSS | News quality becomes a bottleneck |
| L13 | **SQLite / columnar history store** | Deferred after gzip+retention | Larger universe or local history pain |
| L26 | **Incorporate offline libraries into live/paper screen (stage 4)** | When a non-UK market library has PIT constituents, coverage, and data-quality floors comparable to FTSE 350, wire it into paper screening only — not before. | docs/data/library manifests show high coverage + freshness for a target market and FTSE richness goals are met |
| L48 | **Improve Yahoo↔T212 mapping for weak catalogue markets** | After live catalogue fetch, hang_seng/sti show 0% catalogue hits and several EU/AU markets are well below 70% while allowlist still marks them tradable. Tighten ISIN/shortName mapping or trim via unavailable_watch. | Next t212-align after catalogue refresh, or when researching those markets for paper/live trading |

### Research & portfolio product

| # | Idea | Summary | Revisit when |
|---|------|---------|--------------|
| L14 | **Research beyond capped buy tier / short-adversarial mode** | Do not auto-research holds/avoids yet | Capped buy-tier memos prove decision value |
| L15 | **Overlay follow-ons** | Extend research to more buy; email on verdict downgrade; sizing from conviction; verdict_override.yaml | Overlay vs screen-only sim shows benefit |
| L16 | **Multi-turn agent + structured JSON** | Deeper RNS cross-check loops | Cost/runtime budget allows |
| L17 | **Model roadmap after risk family** | Shareholder yield, Novy-Marx, mid-cycle P/E, sector-appropriate value, momentum-as-family | Risk family + adaptive weights validated |
| L18 | **Montier C-Score** | Useful negative filter; after Sloan/FCF conversion if adding one EQ model | After earnings-quality/distress family |
| L19 | **Portfolio concentration / sizing UI** | Sector caps, correlation warnings, size hints | Report should answer what to do with the list |
| L20 | **Synced portfolio backend / dedicated hosting** | Leave Pages+Actions until shared state, login, live refresh, or SLA needs | Multi-device portfolio or private interactive dash |
| L36 | **Gap-fill: ingest — Re-pull full Investegate/RNS HTML or PDF bodies for indexed items tagged** | Re-pull full Investegate/RNS HTML or PDF bodies for indexed items tagged “FY25 Results”, “interim”, and “annual report” rather than Google News wrapper URLs; current index lists 31 filings with `with_body: 0`. | After next weekly email gap-fill pass confirms the gap persists |
| L37 | **Gap-fill: scoring — Override sector classification for plantation/agricultural issuers (e.g.** | Override sector classification for plantation/agricultural issuers (e.g. map to Agriculture/Commodities) so Consumer Defensive peer-relative scores are not applied to palm-oil producers with demonstrated revenue cyclicality. | After next weekly email gap-fill pass confirms the gap persists |
| L38 | **Gap-fill: ingest — Fetch Hikma IR results presentation and annual-report PDFs from hikma.co** | Fetch Hikma IR results presentation and annual-report PDFs from hikma.com and extract cash-flow bridge tables, segment margins, and dividend-policy text into `filings/bodies/`. | After next weekly email gap-fill pass confirms the gap persists |
| L39 | **Gap-fill: ingest — Re-classify UK RNS items by headline pattern (Full Year Results, Half Ye** | Re-classify UK RNS items by headline pattern (Full Year Results, Half Year, Trading Update) and download PDF bodies from Investegate/LSE direct URLs when Ticker RNS API returns empty text. | After next weekly email gap-fill pass confirms the gap persists |
| L40 | **Gap-fill: scoring — Add healthcare overlay flag when trailing FCF is negative AND Piotroski** | Add healthcare overlay flag when trailing FCF is negative AND Piotroski F-Score ≤ 4 — cap adjusted signal at neutral/caution despite composite Strong Buy. | After next weekly email gap-fill pass confirms the gap persists |
| L43 | **Gap-fill: ingest — Fetch company IR results presentation PDF from `photo-me.co.uk` investor** | Fetch company IR results presentation PDF from `photo-me.co.uk` investor pages (listed in `gap_fill_source_map.json` → `company_ir_presentation`) for segment tables, dividend policy, and H1 cash-flow bridges missing from Yahoo. | After next weekly email gap-fill pass confirms the gap persists |
| L55 | **Extend FILINGS_LOOKBACK beyond 800d after CH bodies exist** | Raising FILINGS_LOOKBACK_DAYS / FINANCIAL_YEARS alone does little while UK bodies stay empty (Google wrappers). Once Companies House accounts are ingested, revisit deeper lookback and FILINGS_MAX_ITEMS prioritisation for multi-year statutory history. | CH accounts ingest ships and gap-fill with_body rises for UK memos |
| L56 | **Generic IR PDF crawler (beyond per-issuer L38/L43)** | Prefer a small allowlisted IR-page PDF discovery helper over Hikma/Photo-Me hardcodes. Needs IR homepage map or search-derived PDF URLs; more fragile than Companies House. | CH ingest live and still missing FCF bridges / segment tables that only live in IR decks |
| L57 | **Seed IR allowlist URLs for active memo tickers** | Manual docs/data/research_ir_urls.json MVP is wired; populate URLs for paper-auto / gap-fill UK names that still miss FCF bridges and segment tables after Companies House accounts. | First deepen-sources or gap-fill run with COMPANIES_HOUSE_API_KEY shows CH bodies present but IR-only tables still missing |
| L58 | **OCR for image-only Companies House accounts PDFs** | Shell plc and some other large issuers file image-only group accounts to Companies House; pypdf extracts no text. OCR (or preferring ESEF/iXBRL/SEC 20-F) would unlock CH body depth for those names. | After IR allowlist + SEC dual-list fallbacks still leave CH bodies empty for multiple memo tickers |
| L59 | **Auto-pull SEC 20-F for dual-listed UK memo tickers** | UK deepen currently stays on RNS/CH; dual-listed names like SHEL.L have text-rich SEC 20-F HTML. A regime helper could auto-add recent 20-F/6-K URLs without manual IR allowlist seeding. | More than a handful of FTSE memos need SEC 20-F bodies because CH PDFs are image-only |

### Ops / reliability

| # | Idea | Summary | Revisit when |
|---|------|---------|--------------|
| L22 | **Prove Monday GitHub cron** | Confirm 17 7 * * 1 (or Schedule→dispatch wrapper) | Next Monday after cron window |
| L23 | **Parallel fetch + caching** | Sequential yfinance loop | Weekly runtime becomes painful |
| L25 | **Private live-holdings surveillance bridge** | Watchlist/--add-watch is the safe path; true personal live sync needs non-git storage | Need CI surveillance of personal live book |
| L32 | **Wire live Cursor usage API into library budget ledger** | If Cursor exposes remaining included credits via API, replace estimated spend + manual plan_monthly_usd with live remaining balance for the 10% weekly / surplus-day controls. | Cursor usage/credits API is available to CURSOR_API_KEY |
| L33 | **Signal-priority maintenance refresh for graduated libraries** | Once full weekly refresh is no longer needed, prioritise maintenance (Yahoo metrics/filings cadence) by screen signal / research verdict — e.g. strong_buy and buy first, then hold/alumni — instead of round-robin or uniform caps. | Library richness is stable and Actions runtime or stale floors suggest throttling maintenance_max_tickers away from full |
| L49 | **Default TRADING212_ENV to live or document key/env pairing** | Injected API credentials return 401 on demo.trading212.com but succeed on live. Default env is demo, so bare ftse-library t212-catalogue fails until --env live is passed. | Next credentials rotation or when someone hits catalogue 401 again |
| L51 | **Unify live FTSE research spend into library weekly ledger** | Live ftse-research / email --research-docs use count caps and never call record_estimated_spend. Fold that Cursor usage into the same weekly GBP envelope so library + live research cannot double-spend the allocation. | After a few weeks of enforce_weekly_research_cap with the £30 usage envelope |
| L52 | **Recalibrate estimated_memo_usd from real Cursor bills** | Library spend ledger uses a flat --.40/memo estimate. After constrained weeks, compare estimated_spend vs Cursor usage page and retune estimated_memo_usd. | 2–4 weeks of enforce_weekly_research_cap=true with known memo counts |

---

## Security / hygiene follow-ups

| # | Item | Note | Revisit when |
|---|------|------|--------------|
| S1 | **Rotate any API/SMTP secrets that were pasted or committed** | Git history may still contain old keys even after gitignore fixes | Immediately if keys may still be live |
| S2 | **Re-verify CURSOR_API_KEY in a fresh Cloud Agent** | Secrets may not inject into an already-running pod | Next new Cloud Agent run |
| S3 | **Quote special characters in .env** | Unquoted passwords break source .env | When recreating or editing .env locally |

---

## Suggested review cadence

1. **After each ~4 weekly archives:** check decision-review / cron proof items.
2. **After ~8–12 weeks:** re-open evolution and universe-expansion items.
3. **When runtime or data quality hurts:** UK data, parallel fetch, storage.
4. **When acting on the buy list feels underspecified:** trade plans → sim, sizing UI.
