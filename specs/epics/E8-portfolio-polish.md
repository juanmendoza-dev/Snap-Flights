# E8 — Portfolio Polish

**Status:** STUB. Not specced in depth yet. Runs alongside/after the MVP spine.
**Depends on:** E1, E2 (there has to be a working system to showcase).

## Goal

Make the project land as a portfolio piece: something a reviewer can run in 30 seconds and
an interviewer can probe for an hour.

## Candidate subfeatures (importance)

| Feature | Rating |
|---------|--------|
| Live demo with seeded data | 10 |
| Public accuracy report ("our predictions vs. reality") | 9 |
| ML approach case-study writeup | 8 |
| Architecture diagram + design docs | 8 |
| Scale cost breakdown | 6 |

## Scope boundary

- "Live demo with seeded data" reuses the committed fixture dataset from SF-03 — the demo
  must work with zero API keys and zero collected history.
- The public accuracy report renders the backtest output from E2 — it is a view, not new
  analysis.
- Case-study and design docs are Markdown in the repo (`docs/`), not an artifact/site,
  unless a hosted demo needs a landing page.

## Not specced yet — do not implement.
