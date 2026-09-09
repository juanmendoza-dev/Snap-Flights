# SF-03 — Canonical Schema + Snapshot Store

**Epic:** E1 · **Importance:** 10/10 · **Do this first — it unblocks everyone.**

## Summary

Implement the canonical fare-observation schema (L0 §3) as the single shared module, the
append-only snapshot store (L0 §6), and the committed fixture dataset (L0 §7).

## Depends on

- L0 foundation.
- Open decisions **D1** (language) and **D4** (storage engine) must be resolved first —
  this subfeature can't start until they are.

## Files owned

```
pipeline/schema/**            # the record definition + validators
pipeline/store/**             # read / write / dedup
data/fixtures/**              # routes.csv, fare_observations.parquet, README.md
scripts/gen-fixtures.*        # deterministic fixture generator
tests/schema/**  tests/store/**
```

## What to build

### 1. Schema module (`pipeline/schema/`)

- The fare-observation record with every field from L0 §3, exact names, types, nullability.
- `schema_version = 1`.
- A `validate(record) -> list[violation]` function: type checks, enum checks, IATA format,
  currency format, timestamp is UTC & tz-aware, `amount_minor` is a positive integer,
  `route_key` matches `origin`/`destination`, `return_date` null iff `trip_type == one_way`.
- `observation_id(record) -> str`: SHA-256 hex of the natural key (L0 §6), first 16 chars.
  Deterministic. Unit-tested against fixed vectors.
- A batch validator that returns a structured report (counts by violation type).

### 2. Snapshot store (`pipeline/store/`)

- `write(records)` — append to `data/snapshots/fare_observations/source=…/route_key=…/fetched_date=…/part-{ingest_run_id}.parquet`
  (partition layout from L0 §6). Dedup within the batch on `observation_id`. Refuse (no-op +
  warn) a record whose partition already holds that `observation_id`. Never rewrite a file.
- `read(filters)` — filters: `source`, `route_key` (one or many), `fetched_at` range,
  `depart_date` range, `price_kind`, `data_quality`. Returns canonical records.
- `read` transparently unions `data/snapshots/` with `data/fixtures/fare_observations.parquet`
  when a flag / env (`SNAP_USE_FIXTURES=1`) is set, so downstream code works before real
  data exists. Default off in production.
- No interpretation of prices. No "pick the price for this trip" logic.

### 3. Fixture dataset (`data/fixtures/` + `scripts/gen-fixtures.*`)

Per L0 §7:

- `routes.csv` — ~15 routes with `route_key, origin, destination, region, tier`
  (tiers: `1` hot, `2` warm, `3` cold — SF-04 defines cadence).
- `fare_observations.parquet` — deterministic synthetic history:
  15 routes × ~120 departure dates × daily `fetched_at` for the trailing ~90 days,
  a mix of `calendar_cheapest` and `itinerary` rows, with:
  - a base price per route,
  - a month-of-travel seasonal multiplier,
  - a day-of-week-of-travel multiplier,
  - an advance-purchase curve (prices drift up as `depart_date - fetched_at` shrinks, with noise),
  - ~10 injected error-fare outliers (price 30–60% below expected).
- Fixed RNG seed. `scripts/gen-fixtures.*` reproduces the byte-identical file.
- `data/fixtures/README.md` documents the seed, the price model, and the regen command.

## Done when

- `validate()` rejects each documented bad case and accepts every fixture row.
- `observation_id()` passes fixed-vector tests and is stable across runs.
- `write()` then re-`write()` of the same batch leaves the store with one copy of each observation.
- `read()` with each filter type returns the expected subset of the fixture data.
- `SNAP_USE_FIXTURES=1` makes `read()` return fixture rows with no `data/snapshots/` present.
- CI validates every fixture row against the schema and fails on any violation.
- `scripts/gen-fixtures.*` run twice produces identical output.

## Out of scope

- Collection scheduling (SF-04), quality gates (SF-05), any adapter (SF-01/02).
- Compaction, retention, backfill — later E1 additions.
