# SF-05 — Data-Quality Gates

**Epic:** E1 · **Importance:** 8/10 · Keeps bad data out of the moat.

## Summary

Given a batch of freshly fetched canonical records (plus recent history from the store),
stamp each record's `data_quality` and `quality_flags`, and raise run-level alarms when a
whole batch looks wrong.

## Depends on

- SF-03 (schema + store read for historical context).

## Files owned

```
pipeline/quality/**
tests/quality/**
```

## Record-level checks

Each produces a flag; the resulting `data_quality` is `rejected` if any hard check fails,
`suspect` if only soft checks fail, else `ok`.

| Flag | Kind | Rule |
|------|------|------|
| `schema_invalid` | hard | fails `pipeline/schema` validation |
| `nonpositive_price` | hard | `amount_minor <= 0` |
| `price_above_ceiling` | hard | > configurable absolute ceiling (default `USD 20000` economy) |
| `price_below_floor` | soft | `amount_minor` < 0.35 × trailing-90-day median for that route + advance-purchase bucket (i.e. more than 65% below typical). **Likely an error fare — flag, do not drop.** |
| `price_zscore_extreme` | soft | \|z\| > 4 vs. trailing distribution for route + AP bucket |
| `stale_source_price` | soft | `observed_price_age_seconds` > 7 days |
| `impossible_dates` | hard | `depart_date` in the past at `fetched_at`; `return_date < depart_date` |
| `unknown_airport` | hard | origin/destination not in the route config or IATA reference |

Floors/ceilings/thresholds live in `config/quality.yaml`.

`rejected` records are **still written to the store** (with `data_quality = "rejected"`) so
nothing is silently lost — downstream reads filter them out by default.

## Run-level alarms

Computed over a run's full batch, returned to SF-04 which decides to fail the run:

| Alarm | Default trigger |
|-------|-----------------|
| `empty_run` | 0 records written |
| `mostly_suspect` | > 30% of records `suspect` or `rejected` |
| `price_collapse` | median price for a tier-1 route dropped > 40% vs. its trailing 7-day median |
| `source_silent` | a source that produced data in the last 3 runs produced 0 this run |
| `coverage_drop` | routes covered this run < 60% of the trailing average |

## Done when

- Each record-level flag fires on a crafted fixture case and not otherwise.
- `price_below_floor` marks injected fixture error fares `suspect` (not `rejected`) and
  leaves normal rows `ok`.
- Rejected records reach the store with `data_quality = "rejected"` and are excluded from a
  default `store.read()`.
- Each run-level alarm triggers on a simulated batch and is surfaced to the caller.
- Thresholds are all config-driven; no magic numbers in code.

## Out of scope

- User-facing error-fare *surfacing* (E4) — this is internal hygiene + a signal source.
- Deciding what SF-04 does with an alarm (SF-04 owns that).
