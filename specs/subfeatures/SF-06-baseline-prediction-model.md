# SF-06 — Baseline Percentile / Seasonality Model

**Epic:** E2 · **Importance:** 10/10 · The first version of the headline feature.

## Summary

From the price history in the snapshot store (or fixture dataset), compute for any trip
shape: where today's price sits historically, the typical price path over the next 90 days,
a buy-now / wait verdict with a reason, and a confidence level. **No ML training** — this is
descriptive statistics that anyone can defend cold.

## Depends on

- SF-03 (store + fixture dataset).
- Stack (decision 0001): Python. Use polars or pandas + numpy for the stats; no ML library needed for the baseline.

## Files owned

```
models/features/**
models/baseline/**
models/backtest/**
tests/models/**
```

## Feature builders (`models/features/`)

Read canonical records via `store.read()` (default excludes `data_quality = rejected`).
Produce, per route:

- **Advance-purchase buckets:** days-to-departure grouped (`0-3, 4-7, 8-14, 15-21, 22-30,
  31-45, 46-60, 61-90, 90+`).
- **Trailing price distribution** per (route, AP bucket, month-of-travel, DOW-of-travel) —
  median, p10/p25/p75/p90, count, coefficient of variation.
- Uses `calendar_cheapest` and `itinerary` rows together; when both exist for the same
  (route, depart_date, fetched_date), prefer `itinerary`.

## Baseline model (`models/baseline/`)

`predict(trip_shape, current_price) -> Prediction`:

| Output field | How |
|--------------|-----|
| `price_percentile` | percentile of `current_price` within the trailing-year distribution for (route, AP bucket) |
| `expected_curve` | for each of the next 90 days-to-departure: expected cheapest price = trailing median for that (route, AP bucket, month, DOW), smoothed |
| `verdict` | `book_now` \| `wait` \| `neutral` — rules below |
| `expected_low` | `{price, window_start, window_end}` — the minimum of `expected_curve` and when it occurs, if `wait` |
| `confidence` | `high` \| `medium` \| `low` — from history depth + volatility (rules below) |
| `reason` | plain-language string built from the above (no LLM) |
| `basis` | counts + date range of the observations used — for the "why" panel and auditability |

`current_price`, `price_percentile`, `expected_low` and the `basis` date endpoints are
nullable when the data does not support them (decision 0002 §D3): a missing-data prediction
is `neutral` / `low` with a `data_unavailable_reason` rather than a fabricated price or a
sentinel percentile.

**Verdict rules (defaults, config in `config/baseline.yaml`; semantics pinned in decision 0002 §D4):**
- `book_now` — `price_percentile <= 25` AND `expected_curve` rises ≥ 5% **from its current point** over the remaining horizon.
- `wait` — `price_percentile >= 60` AND `expected_curve` has a point ≥ 7% below **its current point**, strictly after `as_of`, within 60 days.
- `neutral` — otherwise, and always when the curve is empty or `days_to_departure == 0`.

**Confidence rules:**
- `low` if < 100 observations in the (route, AP bucket) cell OR coefficient of variation > 0.35.
- `high` if ≥ 500 observations AND CoV < 0.18.
- `medium` otherwise.

## Backtest harness (`models/backtest/`)

- Walk-forward over the fixture (later: real) history: at each historical `fetched_date`,
  hide the future, ask the model for a verdict, then score against what the price actually did.
- Metrics: buy-vs-wait hit rate, regret ($ paid vs. best achievable), and `wait`
  target/window error — scored for the baseline **and** two reference arms
  (`always_book_now`, and a `hindsight_oracle` labelled as an unachievable lower bound).
  `wait` pays from an executable policy, not the hindsight minimum (decision 0002 §D5).
- Historical-rank consistency check (not forward calibration — decision 0002 §D6).
- Evaluation scenarios are frozen under `models/backtest/scenarios/`, versioned independently
  of results. The fixture is not edited to make the model win.
- Output a JSON report (`models/backtest/reports/latest.json`) — E8's public accuracy page reads this.

## Done when

- `predict()` returns a `Prediction` for every route in the fixture set — fully populated
  where data supports it, and an honest `neutral` / `low` with a `data_unavailable_reason`
  where it does not (decision 0002 §D3).
- Historical-rank consistency holds on the fixture data (a p90 call is beaten ~10% of the time).
- The backtest **produces** hit rate, regret and `wait` window-error numbers for the baseline
  alongside `always_book_now` and the `hindsight_oracle` lower bound. Results are recorded,
  not gated — a loss is reported, not fixed by editing the fixture (decision 0002 §D5).
- `reason` and `basis` are populated and consistent with the numeric outputs.
- Everything works with `SNAP_USE_FIXTURES=1` and no `data/snapshots/`.
- All thresholds are config-driven.

## Out of scope

- Trained/gradient-boosted model, quantile regression, SHAP — E2 Phase 2, separate spec.
- Serving it over HTTP (SF-07).
- Any UI (SF-08).
