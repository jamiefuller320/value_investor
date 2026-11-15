# News event journal (observe-only)

- Generated: `2026-11-15T10:37:52.569143+00:00`
- Source pool: `buy_boundary`
- Mode: `rolling`
- Extractor: `headline-rules-v1.1`
- Cohort tickers: **145** (with news: **100**)
- Articles walked: **2415**
- Issuer rejects: **44**
- Events kept: **316**
- Later filings available: **312**
- Filing-confirmed: **270**
- Seek richer source (insufficient facts): **119**

## Rule confirmation (later filings, not live scores)

| type | events | later filings | confirmed | rate | seek richer | status |
|---|---:|---:|---:|---:|---:|---|
| `leadership` | 59 | 59 | 39 | 66% | 0 | promising |
| `m_and_a` | 218 | 214 | 204 | 95% | 108 | promising |
| `contract` | 13 | 13 | 6 | 46% | 7 | promising |
| `strategy` | 26 | 26 | 21 | 81% | 4 | promising |

## Recent events

| date | ticker | type | confirm | evidence | claim |
|---|---|---|---|---|---|
| 2026-10-21 | `KGF.L` | `leadership` | unconfirmed | sufficient | FTSE 100 Kingfisher (LSE:KGF) Names a New Chief Executive - Kalkine Media |
| 2026-10-22 | `SCT.L` | `m_and_a` | body_match | seek | Why Did Softcat (LSE:SCT) Stock Slip After Strong Full-Year Results And A US Acquisition? - Kalkine Media |
| 2026-10-22 | `IGG.L` | `strategy` | unconfirmed | sufficient | IG Group Eyes U.S. Growth, Prediction Markets and Underdog Deal in New Strategy |
| 2026-10-27 | `GAMA.L` | `m_and_a` | body_match | seek | What Is Next For Gamma Communications (LSE:GAMA) Stock As The Epiris Takeover Moves Toward Completion? - Kalkine Media |
| 2026-10-29 | `GAMA.L` | `m_and_a` | unconfirmed | seek | Takeover Buzz Builds Around Gamma Communications (LSE:GAMA) - Kalkine Media |
| 2026-10-30 | `HFD.L` | `leadership` | unconfirmed | sufficient | Halfords Group PLC: Directorate change - TradingView |
| 2026-10-31 | `VTY.L` | `leadership` | unconfirmed | sufficient | Vistry Group (LSE:VTY) Names A New CFO, Is The Stock Still Cheap? |
| 2026-11-03 | `SHEL.L` | `m_and_a` | unconfirmed | seek | Abu Dhabi’s XRG to acquire Shell’s stake in Australian LNG project |
| 2026-11-03 | `SHEL.L` | `m_and_a` | body_match | sufficient | Shell to divest North West Shelf stake to XRG for $1.5bn |
| 2026-11-04 | `ITV.L` | `m_and_a` | pending | seek | UK government announces public interest investigation into Sky deal to takeover ITV's media arm - Audacy |
| 2026-11-12 | `ATYM.L` | `m_and_a` | pending | sufficient | Atalaya completes $139m acquisition of Tharsis Mining in Spain |
| 2026-11-13 | `BARC.L` | `m_and_a` | body_match | seek | Barclays Capital Securities Reports 2.80% Long Stake in DCC Energy Amid Energy Capital Partners and KKR Takeover Bid - Kalkine Media |

## Insufficient evidence (seek richer source later)

| date | ticker | type | missing | claim |
|---|---|---|---|---|
| 2026-10-15 | `BT-A.L` | `m_and_a` | size, likelihood | FTSE 100 Stock BT Group (LSE:BT.A) Acquisition Announcement: What It Means - Kalkine Media |
| 2026-10-19 | `GAMA.L` | `m_and_a` | size | Mid-Cap Stock Gamma Communications (LSE:GAMA) Takeover Offer Period Rolls On: What It Means - Kalkine Media |
| 2026-10-22 | `SCT.L` | `m_and_a` | size | Why Did Softcat (LSE:SCT) Stock Slip After Strong Full-Year Results And A US Acquisition? - Kalkine Media |
| 2026-10-27 | `GAMA.L` | `m_and_a` | size | What Is Next For Gamma Communications (LSE:GAMA) Stock As The Epiris Takeover Moves Toward Completion? - Kalkine Media |
| 2026-10-29 | `GAMA.L` | `m_and_a` | size, likelihood | Takeover Buzz Builds Around Gamma Communications (LSE:GAMA) - Kalkine Media |
| 2026-11-03 | `SHEL.L` | `m_and_a` | likelihood | Abu Dhabi’s XRG to acquire Shell’s stake in Australian LNG project |
| 2026-11-04 | `ITV.L` | `m_and_a` | size, likelihood | UK government announces public interest investigation into Sky deal to takeover ITV's media arm - Audacy |
| 2026-11-13 | `BARC.L` | `m_and_a` | size | Barclays Capital Securities Reports 2.80% Long Stake in DCC Energy Amid Energy Capital Partners and KKR Takeover Bid - Kalkine Media |

## Coverage notes

- Observe-only: does not modify screen weights, paper knobs, or AI-judgment prompts.
- Input is existing news_manifest title+teaser — no article HTML and no IR crawl.
- Issuer gate reuses headline_relevant_to_issuer plus a short-EPIC currency reject.
- Filing confirmation looks at later filings_index headlines/bodies already on disk.
- Forward returns use archive snapshots (same family as trajectory evidence).
- Insufficient size/likelihood after title+teaser+confirming filing sets seek_richer_source (planned next: guardian_open_platform); nothing is fetched yet.
- Do not promote a rule into the live path until confirmation_rate is promising and later-filing n ≥ 4.
- Archive history is thin (0 snapshots); 12w labels stay sparse.
