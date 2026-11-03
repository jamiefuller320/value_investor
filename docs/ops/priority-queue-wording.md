# Priority queue wording

Wanted-but-not-now work is **queued** behind **P1 → P2 → higher-priority tasks**, not “parked” or dropped.
Reserve **drop** for rejected / indefinite no. Engineering `status=parked` means **attention-blocked**
(CI / preflight / permission / reburn) — a different word; do not rename the status key.

| Lane | Wanted, waiting | Rejected / indefinite no | Blocked needing triage |
|------|-----------------|--------------------------|------------------------|
| Spend / dialogue | `ftse-defer` `open` (`not_now` / `later` / …) | `ftse-defer status … drop` | — |
| Engineering queue | `open` / `pr_open` (priority score) | `cancelled` | `parked` (+ `parked_policy`) |

See [`AGENTS.md`](../../AGENTS.md) spend priorities and Parked vs queued ideas.
Soft migration: historical “park with `ftse-defer`” prose means queue; do not mass-rewrite defer entries.

Do **not** add a fourth equal stream that steals P1/P2.
