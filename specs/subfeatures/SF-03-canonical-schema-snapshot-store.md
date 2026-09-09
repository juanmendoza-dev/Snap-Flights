# SF-03 — Canonical Schema + Snapshot Store

**Epic:** E1 · **Importance:** 10/10 · **Do this first — it unblocks everyone.**

## Summary

Implement the canonical fare-observation schema (L0 §3) as the single shared module, the
append-only snapshot store (L0 §6), and the committed fixture dataset (L0 §7).

## Depends on

- L0 foundation.
- Stack (decision 0001): **Python 3.12+**, **Pydantic** for the schema models,
  **Parquet + DuckDB** for the store, **`uv`** for tooling. All locked — this is ready to start.

## Files owned

```
pipeline/schema/**            # the record definition + validators
pipeline/store/**             # read / write / dedup
data/fixtures/**              # routes.csv, fare_observations.parquet, README.md
scripts/gen_fixtures.py        # deterministic fixture generator
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

- `write(records)` — append a new `part-{ingest_run_id}.parquet` under
  `data/snapshots/fare_observations/source=…/route_key=…/fetched_date=…/` (layout from
  L0 §6). Dedup within the batch on `observation_id` (last wins). Existing files are never
  touched. Calling twice with the same batch is safe.
- `read(filters)` — filters: `source`, `route_key` (one or many), `fetched_at` /
  `fetched_date` range, `depart_date` range, `price_kind`, `data_quality`. Deduplicates
  across part files on `observation_id`, keeping the latest `fetched_at`. Excludes
  `data_quality = "rejected"` unless the caller asks for it. Returns canonical records.
- `read` transparently unions `data/snapshots/` with `data/fixtures/fare_observations.parquet`
  when a flag / env (`SNAP_USE_FIXTURES=1`) is set, so downstream code works before real
  data exists. Default off in production.
- No interpretation of prices. No "pick the price for this trip" logic.

### 3. Fixture dataset (`data/fixtures/` + `scripts/gen_fixtures.py`)

Per L0 §7:

- `routes.csv` — ~15 routes with the exact column schema pinned in **L0 §1** (`route_key,
  origin, destination, region, tier`). Tiers `1` hot / `2` warm / `3` cold.
- `fare_observations.parquet` — deterministic synthetic history:
  15 routes × ~120 departure dates × daily `fetched_at` for the trailing ~90 days.
  **All rows are `trip_type = "one_way"`, `return_date = null`** (MVP is one-way, L0 §8).
  A mix of `calendar_cheapest` and `itinerary` rows, with:
  - a base price per route,
  - a month-of-travel seasonal multiplier,
  - a day-of-week-of-travel multiplier,
  - an advance-purchase curve that is **not uniformly rising**: roughly half the
    (route, departure-month) combinations follow the classic "book early, price climbs as
    departure nears" shape; the other half have a genuine mid-window **dip** (e.g. a 10–18%
    trough somewhere between 45 and 20 days out before rising again). Both shapes are needed
    so SF-06's `wait` verdict and SF-08's two-verdict rendering have data to exercise.
  - ~12 injected error-fare outliers priced **70–85% below** the expected price for their
    cell — deep enough to trip SF-05's `price_below_floor` gate (floor is 0.35× the
    trailing median, so an outlier must sit below that).
- Fixed RNG seed. `scripts/gen_fixtures.py` reproduces the byte-identical file.
- `data/fixtures/README.md` documents the seed, the price model, and the regen command.

## Done when

- `validate()` rejects each documented bad case and accepts every fixture row.
- `observation_id()` passes fixed-vector tests and is stable across runs.
- `write()` then re-`write()` of the same batch: `read()` returns exactly one copy of each
  observation (physical duplicate part files are fine; read-time dedup resolves them).
- `read()` with each filter type returns the expected subset of the fixture data.
- `SNAP_USE_FIXTURES=1` makes `read()` return fixture rows with no `data/snapshots/` present.
- CI validates every fixture row against the schema and fails on any violation.
- `scripts/gen_fixtures.py` run twice produces identical output.

## Out of scope

- Collection scheduling (SF-04), quality gates (SF-05), any adapter (SF-01/02).
- Compaction, retention, backfill — later E1 additions.
