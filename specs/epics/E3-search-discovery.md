# E3 — Search & Discovery

**Status:** STUB. Not specced in depth yet. Comes after the MVP spine (E1 + E2 baseline) runs.
**Depends on:** E1 (fare history), E2 (predictions to overlay).

## Goal

Let people find good trips, not just look up a route they already picked — with the price
prediction layered into the search experience itself.

## Candidate subfeatures (importance)

| Feature | Rating |
|---------|--------|
| Flexible-date heatmap with prediction overlay | 9 |
| "Anywhere" search ranked by predicted deal quality | 8 |
| Explore-by-budget map with predicted prices | 7 |
| Weekend-trip finder from home airport | 6 |
| Seasonality guide per destination | 6 |
| Natural-language search | 4 |
| Trip-inspiration feed | 4 |
| "Surprise me" mode with constraints | 4 |
| Event-driven suggestions | 4 |

## Scope boundary

- Core route search (single O&D, dates, cabin) is part of the E2 UI surface (SF-08), not here.
- This epic is about *discovery* surfaces that fan out across many routes/dates.
- Ranking "deal quality" reuses E2's percentile output — no separate model.

## Open questions for when this is specced

- Does "anywhere" search need broader route coverage than the SF-04 tiered set?
- Natural-language search without an LLM (the conversational assistant was cut) — rules/grammar only?

## Not specced yet — do not implement.
