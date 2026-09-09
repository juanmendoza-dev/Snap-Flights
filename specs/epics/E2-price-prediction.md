# E2 — Price Prediction

**Importance:** 10/10. The headline feature of the whole product.
**Status:** the **baseline** is specced in depth (SF-06, SF-07, SF-08). The trained model
is a stub — separate spec later.
**Depends on:** E1 (needs the snapshot store + fixture dataset).

---

## Goal

Answer one question well: **"Should I book this now or wait?"** — with a reason and a
confidence level, plus a 90-day price outlook and a "this fare is cheaper than X% of the
last year" percentile.

**MVP scope:** one-way, economy, 1 passenger (L0 §8).

## Two phases

### Phase 1 — Baseline (specced now)

No machine learning training. A transparent, defensible model built directly from the
price history in the snapshot store / fixture dataset:

- **Percentile** — where the current price sits in the distribution of observed prices
  for this route + similar advance-purchase window over the trailing year.
- **Seasonality + advance-purchase curve** — typical price by month-of-travel,
  day-of-week of travel, and days-before-departure, per route.
- **Buy-vs-wait call** — derived from the above: if the price is in a low percentile and
  the advance-purchase curve says prices usually rise from here → "book now"; if high
  percentile and curve says a dip is typical → "wait", with an expected window.
- **Confidence** — a function of how much history backs the route and how volatile it is.

This ships first because it works on day one (even on Travelpayouts calendar data alone),
and every claim it makes is explainable cold.

### Phase 2 — Trained model (stub — NOT specced here)

Gradient-boosted model (candidate: LightGBM/XGBoost — Python, per decision 0001) predicting price
direction/magnitude over a horizon, with quantile regression for uncertainty and SHAP for
per-prediction explanations. Needs ~2–3 months of our own collected snapshots before it
can beat the baseline. Gets its own epic/subfeature specs when that data exists. The
earlier draft (`specs/reference/original-draft-spec.md`) sketches the intended approach.

---

## Subfeatures (baseline)

| ID | Title | Depends on | One-line |
|----|-------|-----------|----------|
| SF-06 | Baseline percentile / seasonality model | SF-03 | Feature builders + the baseline model producing prediction + percentile + confidence for a trip shape. |
| SF-07 | Inference API | SF-06 | HTTP endpoint: trip shape in → current price context, 90-day outlook, buy-vs-wait, confidence out. **This is the current-phase finish line.** |
| SF-08 | Buy-vs-wait UI surface | SF-07 | **DEFERRED.** The result screen. Not built in the current phase — owner designs the frontend later with Claude Design (decision 0001 / L0 §8 D3). |

## Build order

1. SF-06 (can start as soon as SF-03's fixture dataset lands).
2. SF-07 — done = the API answers correctly against the fixture data.
3. SF-08 — later, once the frontend stack is chosen.

## Deferred within E2

- Trained model + backtested accuracy number (Phase 2).
- User-facing public accuracy dashboard (belongs to E8, reads E2's backtest output).
- Personal price-target alerts with predicted hit date (E5).
- Model-explanation depth beyond the baseline "why" panel (Phase 2 / SHAP).

## Done when (epic-level, current phase)

- Given a trip shape, the API returns: current price percentile, a 90-day expected-price
  curve, a buy-now / wait verdict with a plain-language reason, and a confidence level.
- Every number is traceable to the snapshot store — no black box in the baseline.
- The backtest harness scores the baseline on held-out fixture history and reports a
  concrete hit-rate for the buy-vs-wait call.
- (SF-08 / the UI showing this to a user is a later phase.)
