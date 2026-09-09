# SF-08 — Buy-vs-Wait UI Surface

**Epic:** E2 · **Importance:** 8/10 · The screen that makes the product feel like "on steroids".

## Summary

The result view: a user enters a route + dates, and sees the verdict (book now / wait), the
90-day price outlook as a chart, the historical percentile, and a "why" panel — all from
one `/predict` call.

## Depends on

- SF-07 (the API + its committed response schema).
- Open decision **D3** (frontend framework).

## Files owned

```
web/**
tests/web/**            # component/e2e tests for this surface
```
(If E3 later adds discovery surfaces, they get their own subdirectories under `web/`;
this spec owns the search-one-route + result flow only.)

## Screens

### 1. Search
Origin, destination, depart date. One-way only for the MVP (L0 §8) — no return-date field,
cabin fixed to economy. Minimal. On submit → call `/predict` (with no `current_price`; the
API fills latest observed).

### 2. Result

- **Verdict banner** — big and clear: `Book now` / `Wait` / `No strong signal`, colored,
  with the one-line `reason` beneath. If `verdict == wait`, show the expected better window
  (`expected_low.window_start`–`window_end`) and the expected price.
- **Price outlook chart** — `expected_curve` plotted over days-to-departure / calendar date,
  with the current price marked and the expected low marked. Follow `dataviz` skill guidance.
- **Percentile strip** — "Cheaper than 66% of the last year" with a simple distribution viz
  placing the current price.
- **Confidence chip** — `high` / `medium` / `low`, with a tooltip explaining it comes from
  how much price history backs this route.
- **"Why" panel** (collapsible) — renders `basis`: number of observations, date range,
  which sources, and the plain-language logic behind the verdict. This is the trust builder;
  make it real, not decorative.
- **Data-quality note** — if the API returns one, show it plainly instead of a confident verdict.

## Behavior

- Loading, thin-data (`confidence: low` / `data_quality_note`), and error states all designed.
- No booking button yet — a disabled/"coming soon" placeholder is fine (E6 fills it).
- Responsive; works on mobile. Theme-aware if the framework supports it.
- No client-side prediction logic — the API is the only source of truth.

## Done when

- Entering any fixture route shows a fully populated result with a rendered chart.
- `wait` and `book_now` verdicts are visually distinct and show the right supporting detail.
- The "why" panel shows real numbers from `basis`.
- Thin-data and error responses render their designed states, not a crash or a blank verdict.
- Component/e2e tests cover the three verdict paths + the thin-data path against a mocked API.

## Out of scope

- Multi-route / flexible-date discovery (E3).
- Actual booking handoff (E6).
- Accounts, saved searches, alerts (E5).
