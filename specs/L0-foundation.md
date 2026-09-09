# L0 — Foundation Spec

**Status:** binding. Every other spec depends on this one.
**Read in full before writing any code.**

This spec defines the shared contracts that let multiple agents build in parallel without
producing incompatible code:

1. Repo layout
2. Naming & ID conventions
3. The canonical fare-observation schema
4. Source-shape schemas (what adapters receive) and how they map to canonical
5. The source-adapter interface contract
6. The snapshot store (layout, natural key, dedup rule)
7. The committed fixture dataset
8. Open decisions (stack, etc.) — what is NOT yet locked

---

## 0. Principles

- **Provenance on every row.** No fare value exists without: which source produced it,
  when it was fetched, and what travel date it describes.
- **Adapters are dumb and swappable.** An adapter fetches from one source and emits
  canonical records. It contains no business logic, no prediction, no storage.
- **The snapshot store is append-only and immutable.** We never update a past observation.
  A price "changing" is a new observation at a new `fetched_at`.
- **Money is never a float.** Integer minor units + ISO currency code, always.
- **All timestamps are UTC, ISO 8601, timezone-aware.** Local times are derived for display
  only, never stored as the source of truth.
- **Everything an agent needs to test must be checked into the repo** (the fixture dataset).
  Nobody waits for live data to be collected before they can build.

---

## 1. Repo layout

Directory names are binding. The language/framework inside each is an open decision
(§8), but the boundaries are not.

```
snap-flights/
├── specs/                      # this folder — source of truth for scope
├── data/
│   ├── fixtures/               # committed seed dataset (see §7) — schema-valid, deterministic
│   │   ├── fare_observations.parquet
│   │   ├── routes.csv
│   │   └── README.md
│   └── snapshots/              # gitignored — the real append-only store, built at runtime
├── pipeline/
│   ├── adapters/               # one module per source (travelpayouts, fastflights, ...)
│   ├── schema/                 # canonical record definition + validators (single source of truth)
│   ├── store/                  # snapshot store read/write
│   ├── quality/                # data-quality gates
│   ├── scheduler/              # collection orchestration + route prioritization
│   └── README.md
├── models/
│   ├── baseline/               # percentile / seasonality model (E2)
│   ├── features/               # feature builders reading from the snapshot store
│   ├── backtest/               # backtesting harness
│   └── README.md
├── api/                        # inference + search HTTP API
├── web/                        # frontend
├── shared/                     # cross-cutting types/constants shared by >1 top-level dir
├── scripts/                    # one-off + operational scripts
├── tests/                      # cross-cutting / integration tests (unit tests live beside code)
└── README.md
```

**Rule:** a subfeature spec's *Files owned* section lists paths under exactly one of these
trees (plus its own test files). If two subfeatures would need the same file, that file
belongs in `shared/` and its shape is pinned in a spec before either starts.

---

## 2. Naming & ID conventions

| Thing | Convention | Example |
|-------|-----------|---------|
| Directories, files | `kebab-case` | `route-prioritization.md` |
| Airport codes | IATA, uppercase, 3 letters | `JFK`, `LHR` |
| Route key | `{ORIGIN}-{DEST}`, directional | `JFK-LHR` (≠ `LHR-JFK`) |
| Currency | ISO 4217, uppercase | `USD`, `EUR` |
| Cabin class | lowercase enum: `economy` `premium_economy` `business` `first` | `economy` |
| Timestamps | UTC, ISO 8601 with `Z` | `2026-09-09T14:30:00Z` |
| Travel dates (no time) | ISO date | `2026-12-24` |
| Source id | lowercase, stable, matches adapter dir name | `travelpayouts`, `fastflights` |
| Money | integer minor units + separate currency field | `amount_minor: 45900`, `currency: USD` → $459.00 |
| Spec ids | `E{n}` epics, `SF-{nn}` subfeatures | `E1`, `SF-03` |

**Observation id:** a deterministic hash (SHA-256, hex, first 16 chars) of the natural key
(§6). Adapters compute it; it is not random. Same natural key → same id, always.

---

## 3. Canonical fare-observation schema

The single record type that flows through the whole pipeline. One row = **one price seen
for one trip shape, from one source, at one moment in time.**

Defined once in `pipeline/schema/`. All producers and consumers import from there.
Changing this schema is a spec-level change, never done ad hoc.

| Field | Type | Null? | Unit / format | Notes |
|-------|------|-------|---------------|-------|
| `observation_id` | string(16) | no | hex | deterministic hash of natural key (§6) |
| `source` | string | no | enum | `travelpayouts` \| `fastflights` \| … — matches adapter dir |
| `source_native_id` | string | yes | — | the source's own id for this result, if any (for debugging) |
| `fetched_at` | timestamp | no | UTC ISO 8601 | when our adapter received this data |
| `observed_price_age_seconds` | int64 | yes | seconds | if the source reveals how stale its own price is (Travelpayouts cache age); null if unknown |
| `origin` | string(3) | no | IATA | |
| `destination` | string(3) | no | IATA | |
| `route_key` | string(7) | no | `ORG-DST` | derived; stored for query convenience |
| `depart_date` | date | no | ISO date | outbound travel date |
| `return_date` | date | yes | ISO date | null = one-way |
| `trip_type` | string | no | enum | `one_way` \| `round_trip` |
| `cabin` | string | no | enum | see §2 |
| `passengers` | int64 | no | count | adults; MVP always `1` |
| `stops_outbound` | int64 | yes | count | 0 = nonstop; null if source gives only a route-level cheapest |
| `stops_return` | int64 | yes | count | null for one-way or when unknown |
| `carrier_primary` | string | yes | IATA airline | marketing carrier of first segment; null if source is itinerary-agnostic |
| `amount_minor` | int64 | no | minor units | total price for `passengers`, all-in as the source reports it |
| `currency` | string(3) | no | ISO 4217 | |
| `price_kind` | string | no | enum | `itinerary` (a specific bookable option) \| `calendar_cheapest` (source's cheapest for that date, no fixed itinerary) |
| `data_quality` | string | no | enum | `ok` \| `suspect` \| `rejected` — set by quality gates (SF-05), default `ok` |
| `quality_flags` | string[] | yes | list of enum | e.g. `["price_below_floor"]`; null/empty when `ok` |
| `ingest_run_id` | string | no | uuid | the collection run that produced this row (SF-04) |
| `schema_version` | int64 | no | — | starts at `1`; bump on any breaking schema change |

### Notes for adapter authors

- Emit `amount_minor` exactly as the source states the total for **1 adult**. Do not
  convert currency. Do not add or remove fees.
- If a source gives a route-level "cheapest for this day" with no itinerary detail
  (Travelpayouts), set `price_kind = calendar_cheapest`, fill `stops_*`/`carrier_primary`
  only if actually provided, leave the rest null.
- If a source gives a specific option (fast-flights), set `price_kind = itinerary` and
  fill `stops_*` and `carrier_primary`.
- Never set `data_quality` yourself beyond the default `ok` — that's the gates' job.

---

## 4. Source-shape schemas → canonical mapping

Each adapter spec (SF-01, SF-02) contains the full field-by-field mapping. L0 pins only
the two *shapes* we support:

| Shape | Produced by | `price_kind` | Typical fields present |
|-------|-------------|--------------|------------------------|
| **Price calendar** | Travelpayouts | `calendar_cheapest` | route, date, cheapest amount, sometimes stop count; no itinerary |
| **Itinerary** | fast-flights, later Duffel/airlines | `itinerary` | route, date(s), price, stops, carrier, duration |

A third shape (flight *status/position* data, e.g. OpenSky) is **out of scope for the fare
pipeline** — it feeds trip-quality features (E7) through a separate path, not this schema.

---

## 5. Source-adapter interface contract

Behavioral contract, stack-neutral. The concrete signature lands once the language is
chosen (§8), but these semantics are binding now.

### An adapter is

A module in `pipeline/adapters/{source}/` exposing one entry point that takes a
**fetch request** and returns a **fetch result**.

### Fetch request (input)

| Field | Type | Notes |
|-------|------|-------|
| `origin` | string(3) | IATA |
| `destination` | string(3) | IATA |
| `depart_date_from` | date | inclusive start of the departure-date window to fetch |
| `depart_date_to` | date | inclusive end; adapters may fetch a whole month in one call if the source supports it |
| `trip_type` | enum | `one_way` \| `round_trip` |
| `return_offset_days` | int64 \| null | for round trips: nights at destination; null for one-way |
| `cabin` | enum | |
| `ingest_run_id` | uuid | passed straight through onto every emitted record |

### Fetch result (output)

| Field | Type | Notes |
|-------|------|-------|
| `records` | canonical fare-observation[] | may be empty; never null |
| `outcome` | enum | `ok` \| `partial` \| `empty` \| `rate_limited` \| `source_error` \| `blocked` |
| `error_detail` | string \| null | human-readable; required when outcome ≠ `ok`/`empty` |
| `source_request_count` | int64 | how many upstream HTTP calls this fetch made (for budgeting) |
| `retry_after_seconds` | int64 \| null | set on `rate_limited` when the source tells us |

### Rules

- **Never throw for an expected failure.** Network errors, rate limits, blocks, empty
  results → return a `fetch result` with the right `outcome`. Only truly unexpected bugs
  may raise.
- **`partial`** = some records returned but the fetch was cut short (e.g. rate limited
  mid-window). The scheduler will re-queue the gap.
- **Idempotent.** Calling with the same request twice produces records with the same
  `observation_id`s (because the natural key is deterministic). The store dedups.
- **Politeness is the adapter's job.** Rate limiting, backoff, jitter, and (for
  fast-flights) request pacing live inside the adapter, configured via env, with safe
  defaults documented in the adapter spec.
- **No storage, no side effects** beyond outbound fetches and logging. The adapter returns
  data; the scheduler decides what to do with it.
- **Stateless between calls** except for an in-process rate-limiter.

---

## 6. Snapshot store

### Natural key (what makes two rows "the same observation")

```
(source, origin, destination, depart_date, return_date, cabin, passengers,
 trip_type, stops_outbound, stops_return, carrier_primary, price_kind, fetched_at)
```

`fetched_at` is part of the key on purpose: **the same trip shape fetched at two different
times is two observations** — that's the time series. Two rows identical on everything
*including* `fetched_at` are true duplicates (e.g. a retry) and the store keeps one.

`observation_id` = `sha256(natural key fields joined with "|")[:16]`.

### Layout

Append-only columnar files under `data/snapshots/`, partitioned:

```
data/snapshots/fare_observations/
  source={source}/
    route_key={ORG-DST}/
      fetched_date={YYYY-MM-DD}/
        part-{ingest_run_id}.parquet
```

- Partition by `fetched_date` (UTC date of `fetched_at`), not travel date — writes are
  always to today's partition, reads for training scan ranges.
- One file per `(source, route, fetched_date, ingest_run)`. Never rewrite a file.
- `data/snapshots/` is **gitignored**. The committed equivalent is `data/fixtures/` (§7).

### Store interface (behavioral)

- `write(records[])` — append; dedup within the batch on `observation_id`; refuse to write
  a record whose `fetched_date` partition already contains that `observation_id`.
- `read(filters)` — by source, route(s), `fetched_at` range, `depart_date` range. Returns
  canonical records. This is the only way models and the API get fare data.
- The store does not interpret prices, does not pick "the" price for a trip — that's the
  model/API layer.

---

## 7. Committed fixture dataset

**Why:** on day one there is zero collected history. Without a committed dataset, every
agent building the store, the model, the API, or the UI is blocked for months. The fixture
is also the seed for the public demo (E8).

`data/fixtures/` contains:

| File | Contents |
|------|----------|
| `routes.csv` | ~15 routes: `route_key, origin, destination, region, tier` — the fixed MVP route set |
| `fare_observations.parquet` | **deterministic** synthetic history: the 15 routes × ~120 departure dates × daily `fetched_at` for ~90 days, both `price_kind` values, realistic seasonality + day-of-week + advance-purchase curves + a handful of injected error-fare outliers |
| `README.md` | how it was generated, the seed, the price model used, how to regenerate |

Requirements:

- Every row validates against the §3 schema (CI enforces this).
- Fully deterministic: a `scripts/gen-fixtures.*` script with a fixed random seed
  reproduces the exact file. Regeneration is a deliberate, reviewed change.
- Realistic enough that the baseline model (SF-06) produces sane output and the backtest
  has something to score.
- Small enough to live in git (target < 10 MB; use compression).
- Clearly synthetic — no claim that these are real observed prices.

`SF-03` owns creating this. Everything downstream may assume it exists.

---

## 8. Open decisions (NOT locked)

These are deferred deliberately. Do not resolve them unilaterally in a subfeature spec or
in code — they get decided with a pros/cons review first, then recorded here.

| # | Decision | Notes / leading candidate |
|---|----------|---------------------------|
| D1 | Primary language for pipeline + models | earlier draft assumed Python + LightGBM/XGBoost + SHAP; not binding |
| D2 | API framework | — |
| D3 | Frontend framework | earlier draft said "minimal, backend/ML project" — but E2/E3 need real UI surfaces |
| D4 | Storage engine for the snapshot store | Parquet files + an embedded query engine (e.g. DuckDB) is the working assumption in §6; confirm |
| D5 | Orchestrator for collection runs | cron vs. a workflow engine (Prefect/Dagster free tier) |
| D6 | Package manager / repo tooling / monorepo layout | — |
| D7 | Hosting (free tier) for the collectors and API | Oracle Cloud Always Free mentioned in research |
| D8 | Auth system — whether MVP has accounts at all | earlier draft rated `6/10`; alerts (E5) need it, MVP spine does not |

Until D1–D4 are settled, subfeature specs describe **behavior and contracts**, and
implementation waits. `SF-03` (schema + store) is the natural first thing to unblock once
D1 and D4 land.

---

## 9. Glossary

- **Observation** — one price, one trip shape, one source, one moment. The atomic row.
- **Trip shape** — origin, destination, dates, cabin, trip type, stops, carrier. Everything
  that defines *what* is being priced, minus the price and the time.
- **Price calendar** — a source's cheapest price per day for a route, without itinerary
  detail. Travelpayouts' native shape.
- **Snapshot store** — the append-only history of all observations. The moat.
- **Fixture dataset** — committed synthetic history so agents can build before real data exists.
- **Route tier** — priority band for a route (how often we collect it). Defined in SF-04.
- **Ingest run** — one scheduled pass of the collector; `ingest_run_id` stamps its output.
- **Baseline model** — percentile + seasonality prediction from calendar data; no training.
  Ships first (SF-06). The trained model is a later, separate spec.
