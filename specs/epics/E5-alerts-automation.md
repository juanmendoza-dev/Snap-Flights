# E5 — Alerts & Automation

**Status:** STUB. Not specced in depth yet. Explicitly a *later* epic — kept in scope, built after E1–E3.
**Depends on:** E1 (fare history), E2 (predictions), and an auth/accounts system (open decision D8).

## Goal

Tell people when to act — and only when to act. The differentiator vs. every other price
alert: alerts fire on the **model's** judgment ("book now, it won't get lower"), not on a
dumb threshold.

## Candidate subfeatures (importance)

| Feature | Rating |
|---------|--------|
| Smart alerts that fire only when the prediction says act | 9 |
| Watchlist with per-trip target price + deadline | 8 |
| Ranked-deals digest (email/push) | 6 |
| Price-drop-after-booking monitor + refund/rebook workflow | 5 |
| Shareable price-watch links for group trips | 5 |
| Auto-rebook when a cheaper equivalent appears (with approval) | 4 |

## Scope boundary

- Requires user accounts — MVP spine does not. Auth is open decision D8.
- Needs a notification transport (email at minimum). Pick a free-tier provider when specced.
- "Smart" alert logic is a thin consumer of E2's buy-vs-wait output, not new modeling.
- The scheduler that evaluates watchlists is related to but separate from E1's collection
  scheduler (SF-04) — different cadence, different trigger.

## Not specced yet — do not implement.
