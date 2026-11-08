# News event journal (observe-only)

- Generated: `2026-11-08T10:36:49.835979+00:00`
- Source pool: `buy_boundary`
- Mode: `rolling`
- Extractor: `headline-rules-v1.1`
- Cohort tickers: **126** (with news: **81**)
- Articles walked: **9269**
- Issuer rejects: **131**
- Events kept: **240**
- Later filings available: **237**
- Filing-confirmed: **202**
- Seek richer source (insufficient facts): **78**

## Rule confirmation (later filings, not live scores)

| type | events | later filings | confirmed | rate | seek richer | status |
|---|---:|---:|---:|---:|---:|---|
| `leadership` | 44 | 44 | 26 | 59% | 0 | promising |
| `m_and_a` | 165 | 162 | 155 | 96% | 69 | promising |
| `contract` | 11 | 11 | 4 | 36% | 7 | weak |
| `strategy` | 20 | 20 | 17 | 85% | 2 | promising |

## Recent events

| date | ticker | type | confirm | evidence | claim |
|---|---|---|---|---|---|
| 2026-10-15 | `BT-A.L` | `m_and_a` | pending | seek | FTSE 100 Stock BT Group (LSE:BT.A) Acquisition Announcement: What It Means - Kalkine Media |
| 2026-10-15 | `EZJ.L` | `m_and_a` | body_match | sufficient | Apollo's Takeover of EasyJet Heads for Q1 Close Amid Opposition From European Labor Unions |
| 2026-10-15 | `EZJ.L` | `m_and_a` | body_match | sufficient | Pilots fear for jobs after £5.7bn easyJet takeover |
| 2026-10-17 | `KGF.L` | `leadership` | unconfirmed | sufficient | Is CEO Succession Altering The Investment Case For Kingfisher (LSE:KGF)? |
| 2026-10-20 | `HOC.L` | `m_and_a` | body_match | sufficient | Sika acquires Azpects in UK before October 23 results for Sika stock - ad-hoc-news.de |
| 2026-10-21 | `KGF.L` | `leadership` | unconfirmed | sufficient | FTSE 100 Kingfisher (LSE:KGF) Names a New Chief Executive - Kalkine Media |
| 2026-10-22 | `SCT.L` | `m_and_a` | body_match | seek | Why Did Softcat (LSE:SCT) Stock Slip After Strong Full-Year Results And A US Acquisition? - Kalkine Media |
| 2026-10-22 | `IGG.L` | `strategy` | unconfirmed | sufficient | IG Group Eyes U.S. Growth, Prediction Markets and Underdog Deal in New Strategy |
| 2026-10-30 | `HFD.L` | `leadership` | unconfirmed | sufficient | Halfords Group PLC: Directorate change - TradingView |
| 2026-11-03 | `SHEL.L` | `m_and_a` | unconfirmed | seek | Abu Dhabi’s XRG to acquire Shell’s stake in Australian LNG project |
| 2026-11-03 | `SHEL.L` | `m_and_a` | body_match | sufficient | Shell to divest North West Shelf stake to XRG for $1.5bn |
| 2026-11-04 | `ITV.L` | `m_and_a` | pending | seek | UK government announces public interest investigation into Sky deal to takeover ITV's media arm - Audacy |

## Insufficient evidence (seek richer source later)

| date | ticker | type | missing | claim |
|---|---|---|---|---|
| 2026-09-28 | `GEN.L` | `m_and_a` | size | Gen Digital CEO addresses GoDaddy acquisition rumors - Yahoo Finance UK |
| 2026-09-29 | `VSVS.L` | `m_and_a` | size | Vesuvius Shares Rise 23% After Company Confirms RHI Magnesita Takeover Proposal - Yahoo Finance UK |
| 2026-10-05 | `VSVS.L` | `m_and_a` | size | Will Vesuvius (LSE:VSVS) Shares Keep Climbing After the RHI Magnesita Takeover Proposal This Week? - Kalkine Media |
| 2026-10-09 | `BT-A.L` | `m_and_a` | size, likelihood | BT Group (LSE:BT.A): What Does Its Acquisition Of TalkTalk Mean For UK Broadband Competition This Week? - Kalkine Media |
| 2026-10-15 | `BT-A.L` | `m_and_a` | size, likelihood | FTSE 100 Stock BT Group (LSE:BT.A) Acquisition Announcement: What It Means - Kalkine Media |
| 2026-10-22 | `SCT.L` | `m_and_a` | size | Why Did Softcat (LSE:SCT) Stock Slip After Strong Full-Year Results And A US Acquisition? - Kalkine Media |
| 2026-11-03 | `SHEL.L` | `m_and_a` | likelihood | Abu Dhabi’s XRG to acquire Shell’s stake in Australian LNG project |
| 2026-11-04 | `ITV.L` | `m_and_a` | size, likelihood | UK government announces public interest investigation into Sky deal to takeover ITV's media arm - Audacy |

## Coverage notes

- Observe-only: does not modify screen weights, paper knobs, or AI-judgment prompts.
- Input is existing news_manifest title+teaser — no article HTML and no IR crawl.
- Issuer gate reuses headline_relevant_to_issuer plus a short-EPIC currency reject.
- Filing confirmation looks at later filings_index headlines/bodies already on disk.
- Forward returns use archive snapshots (same family as trajectory evidence).
- Insufficient size/likelihood after title+teaser+confirming filing sets seek_richer_source (planned next: guardian_open_platform); nothing is fetched yet.
- Do not promote a rule into the live path until confirmation_rate is promising and later-filing n ≥ 4.
- Archive history is thin (0 snapshots); 12w labels stay sparse.
