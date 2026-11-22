# News event journal (observe-only)

- Generated: `2026-11-22T10:38:17.721985+00:00`
- Source pool: `buy_boundary`
- Mode: `rolling`
- Extractor: `headline-rules-v1.1`
- Cohort tickers: **145** (with news: **100**)
- Articles walked: **2669**
- Issuer rejects: **50**
- Events kept: **320**
- Later filings available: **317**
- Filing-confirmed: **273**
- Seek richer source (insufficient facts): **121**

## Rule confirmation (later filings, not live scores)

| type | events | later filings | confirmed | rate | seek richer | status |
|---|---:|---:|---:|---:|---:|---|
| `leadership` | 60 | 60 | 39 | 65% | 0 | promising |
| `m_and_a` | 221 | 218 | 207 | 95% | 110 | promising |
| `contract` | 13 | 13 | 6 | 46% | 7 | promising |
| `strategy` | 26 | 26 | 21 | 81% | 4 | promising |

## Recent events

| date | ticker | type | confirm | evidence | claim |
|---|---|---|---|---|---|
| 2026-10-29 | `GAMA.L` | `m_and_a` | unconfirmed | seek | Takeover Buzz Builds Around Gamma Communications (LSE:GAMA) - Kalkine Media |
| 2026-10-30 | `HFD.L` | `leadership` | unconfirmed | sufficient | Halfords Group PLC: Directorate change - TradingView |
| 2026-10-31 | `VTY.L` | `leadership` | unconfirmed | sufficient | Vistry Group (LSE:VTY) Names A New CFO, Is The Stock Still Cheap? |
| 2026-11-01 | `RHIM.L` | `m_and_a` | unconfirmed | sufficient | RHI Magnesita (LSE:RHIM) Stock May Be Reasonable On Fresh Takeover Deadline News |
| 2026-11-03 | `SHEL.L` | `m_and_a` | unconfirmed | seek | Abu Dhabi’s XRG to acquire Shell’s stake in Australian LNG project |
| 2026-11-03 | `SHEL.L` | `m_and_a` | body_match | sufficient | Shell to divest North West Shelf stake to XRG for $1.5bn |
| 2026-11-04 | `ITV.L` | `m_and_a` | pending | seek | UK government announces public interest investigation into Sky deal to takeover ITV's media arm - Audacy |
| 2026-11-12 | `ATYM.L` | `m_and_a` | body_match | sufficient | Atalaya completes $139m acquisition of Tharsis Mining in Spain |
| 2026-11-13 | `BARC.L` | `m_and_a` | body_match | seek | Barclays Capital Securities Reports 2.80% Long Stake in DCC Energy Amid Energy Capital Partners and KKR Takeover Bid - Kalkine Media |
| 2026-11-18 | `VCT.L` | `leadership` | unconfirmed | sufficient | Does Victrex (LSE:VCT) Stock Gain Momentum This Week As A New CFO Completes Its Leadership Reset? - Kalkine Media |
| 2026-11-18 | `GSK.L` | `m_and_a` | body_match | seek | GSK Wins FDA Approval for Nuvalent-Acquired Nelkarmi in Lung Cancer |
| 2026-11-20 | `BARC.L` | `m_and_a` | body_match | seek | Barclays Capital Securities Reveals 3.08% Stake in DCC Energy PLC Amid Energy Capital Partners and KKR Takeover Bid - Kalkine Media |

## Insufficient evidence (seek richer source later)

| date | ticker | type | missing | claim |
|---|---|---|---|---|
| 2026-10-22 | `SCT.L` | `m_and_a` | size | Why Did Softcat (LSE:SCT) Stock Slip After Strong Full-Year Results And A US Acquisition? - Kalkine Media |
| 2026-10-27 | `GAMA.L` | `m_and_a` | size | What Is Next For Gamma Communications (LSE:GAMA) Stock As The Epiris Takeover Moves Toward Completion? - Kalkine Media |
| 2026-10-29 | `GAMA.L` | `m_and_a` | size, likelihood | Takeover Buzz Builds Around Gamma Communications (LSE:GAMA) - Kalkine Media |
| 2026-11-03 | `SHEL.L` | `m_and_a` | likelihood | Abu Dhabi’s XRG to acquire Shell’s stake in Australian LNG project |
| 2026-11-04 | `ITV.L` | `m_and_a` | size, likelihood | UK government announces public interest investigation into Sky deal to takeover ITV's media arm - Audacy |
| 2026-11-13 | `BARC.L` | `m_and_a` | size | Barclays Capital Securities Reports 2.80% Long Stake in DCC Energy Amid Energy Capital Partners and KKR Takeover Bid - Kalkine Media |
| 2026-11-18 | `GSK.L` | `m_and_a` | size | GSK Wins FDA Approval for Nuvalent-Acquired Nelkarmi in Lung Cancer |
| 2026-11-20 | `BARC.L` | `m_and_a` | size | Barclays Capital Securities Reveals 3.08% Stake in DCC Energy PLC Amid Energy Capital Partners and KKR Takeover Bid - Kalkine Media |

## Coverage notes

- Observe-only: does not modify screen weights, paper knobs, or AI-judgment prompts.
- Input is existing news_manifest title+teaser — no article HTML and no IR crawl.
- Issuer gate reuses headline_relevant_to_issuer plus a short-EPIC currency reject.
- Filing confirmation looks at later filings_index headlines/bodies already on disk.
- Forward returns use archive snapshots (same family as trajectory evidence).
- Insufficient size/likelihood after title+teaser+confirming filing sets seek_richer_source (planned next: guardian_open_platform); nothing is fetched yet.
- Do not promote a rule into the live path until confirmation_rate is promising and later-filing n ≥ 4.
- Archive history is thin (0 snapshots); 12w labels stay sparse.
