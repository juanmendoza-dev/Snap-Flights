# Decision 0002 — Prediction semantics and evaluation

**Date:** 2026-09-09
**Status:** accepted
**Resolves:** review findings P1, P2, P6, P7 (see `specs/review/03-prediction.md`); the
prediction-product and purchase-policy gaps in `specs/review/09-information-needed.md`.
**Amends:** `specs/subfeatures/SF-06-baseline-prediction-model.md` (Done when, verdict rules,
Prediction table), `specs/implementation/SF-06-build.md`, `specs/implementation/SF-07-build.md`
(`PredictResponse` nullability).

---

## Context

The review found the SF-06 build spec self-contradictory in three places that block
implementation: the empty-store response cannot satisfy its own type (P1), the verdict rules
score a price-level difference as if it were a future move (P2), and the backtest rewards a
hindsight oracle while instructing the implementer to tune the fixture until the model wins
(P6). These need product decisions, not code.

## Decisions

### D1 — The product is advisory. No purchase happens on snap-flights.

snap-flights predicts and recommends; it never sells a ticket. The user acts on the
recommendation elsewhere (an airline, an OTA, Google Flights). This does **not** remove the
buy/wait verdict — the verdict is the headline feature. It means there is no checkout, no
cart, no booking record, and the backtest models the *decision* ("book now vs wait"), not a
transaction on our side.

### D2 — Booking deadline is the departure date.

A `wait` recommendation may point to any date in `(as_of, depart_date]`. There is no earlier
cutoff for the MVP. When `days_to_departure == 0` the verdict is never `wait` — there is no
future left to wait into. A tighter, source-informed deadline is a later decision once real
purchase-window data exists.

### D3 — Missing data yields an honest neutral response, with nullable fields.

The `Prediction` / `PredictResponse` contract is amended so these may be `null`:
`current_price`, `price_percentile`, `expected_low`, and the `basis.from` / `basis.to` date
endpoints. When data is missing:

- `verdict = "neutral"`, `confidence = "low"`.
- `data_unavailable_reason` (new, machine-readable enum: `no_current_price`,
  `no_route_history`, `thin_route_history`, `departure_in_past`) is set, and
  `data_quality_note` carries the human sentence.
- Counts in `basis` are `0`; `basis.sources` is `[]`.
- If the caller supplied a price, it is echoed back as `current_price`
  (`source = user_supplied`) even with no history. `price_percentile` stays `null` in that
  case — a computed rank of 50 and "no data" must not look alike.

A fully-populated prediction still has every field non-null; "populated" now means "every
field the available data supports", not "every field regardless".

### D4 — The verdict compares against the curve's current point, not just the quote.

Pinned semantics, replacing SF-06-build §4.3–4.4:

- The curve result carries `as_of` and `dtd_now` explicitly (not inferred from the first
  surviving point). Verdict and `find_expected_low` both use the **request** horizon.
- **Eligible future points** for `wait`: curve points with
  `days_to_departure` in `[max(0, dtd_now - search_horizon_days), dtd_now - 1]` — strictly
  after `as_of`.
- `wait` requires **both**:
  1. `price_percentile >= wait.min_percentile` — the quote is dear relative to history; and
  2. `min(eligible future curve value) <= curve_value_at(dtd_now) * (1 - wait.min_curve_drop_pct/100)`
     — the curve itself predicts a dip from where it is now.
  `expected_low` is chosen from exactly the eligible future points that clear condition 2.
- `book_now` requires **both**:
  1. `price_percentile <= book_now.max_percentile`; and
  2. `max(curve value over `[max(0, dtd_now - horizon_days), dtd_now]`) >= curve_value_at(dtd_now) * (1 + book_now.min_curve_rise_pct/100)`
     — a rise **from the current point**, not a maximum anywhere relative to the quote.
- `neutral` otherwise, and unconditionally when the curve is empty or `dtd_now == 0`.
- `reason` text must describe condition 2 accurately ("prices on this route usually dip
  about X% by {date}"), never restate condition 1 as if it were a forecast.

### D5 — The backtest reports; it does not gate, and it does not use hindsight to pay.

Replacing SF-06-build §5 scoring and the SF-06 Done-when win bullet:

- **Removed:** the instruction to widen the dip fraction / deepen the trough and regenerate
  the fixture until the baseline beats always-`book_now`. Fitting the evaluation data to the
  model is not allowed. A loss is reported.
- **Removed:** the mandatory "hit rate better than always-`book_now`" gate in SF-06's
  *Done when*. It becomes: the backtest **produces** hit rate, regret and window-error
  numbers for the baseline alongside two reference arms.
- **Reference arms**, both scored on the same sample set:
  - `always_book_now` — every verdict forced to `book_now`.
  - `hindsight_oracle` — pays `min` observed price in the window. Explicitly labelled a
    lower bound no real user can achieve; never the baseline's own score.
- **`wait` paid price** comes from an executable policy, not `min`: the first observed quote
  at or below the predicted `expected_low.amount_minor` within
  `[expected_low.window_start, expected_low.window_end]`; if none appears, the observed price
  on the deadline (departure day, or the latest `fetched_date <= depart_date`).
- **`book_now` paid price** is `price_now`.
- New per-sample metrics for `wait`: `target_error_minor` (paid − predicted target) and
  `window_hit` (did any in-window observation reach the target). A `wait` whose window is
  wrong now scores badly even if some other date was cheap.
- Evaluation scenarios are frozen and versioned independently of results
  (`models/backtest/scenarios/`), separate from the fixture used for feature tests.

### D6 — The percentile "calibration" report is renamed and rescoped.

Per P7: the trailing-sample rank checked against the same trailing sample is
**historical-rank consistency**, not forecast calibration. Rename the report section and its
test. Keep the mid-rank formula `round(100 * (below + 0.5*equal) / n)`. Do not claim it is a
forward probability. Tolerances are set from the first clean run and recorded in the commit
message (unchanged from the build spec).

## Deferred — tracked, not resolved here

These review findings need real collected data or larger design work and do **not** block the
SF-06 build:

| Finding | Why deferred |
|---|---|
| P3 (curve gaps, calendar grid, broad-fallback minimum count) | Partly handled by the explicit `as_of`/`dtd_now` carry in D4; the rest (never smoothing across unsupported gaps, capping confidence by future support) is a Phase-2 curve rework. |
| P4 (observation count measures grid density, not independent history) | Needs real multi-day collection to define distinct-collection-day thresholds. Until then the fixture thresholds are descriptive coverage bands. |
| P5 (source switching / stale-price age policy) | Needs the ingestion layer (SF-01/02/05) and real source timestamps. |
| P8 (walk-forward censoring and revision-availability rules) | Needs real history with outages and quality corrections. |

Record these against E2 Phase 2.

## Consequences

- SF-06-build.md §4.1 types gain nullability on four fields plus `data_unavailable_reason`;
  §4.3–4.4 verdict logic changes to "vs current curve point"; §5 scoring is rewritten.
- SF-06 L2 *Done when* loses the win gate and gains a "reports three arms" bullet.
- SF-07-build.md `PredictResponse` must mirror the nullable fields; its OpenAPI regenerates
  from the empty-store and thin-data branches. Flag for the SF-07 implementer.
- The §6 test "asserts every field non-null" is split into a populated-route case and an
  empty/thin case.
- `models/backtest/scenarios/` is a new owned directory.
