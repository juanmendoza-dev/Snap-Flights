# SF-01 — Travelpayouts Source Adapter

**Epic:** E1 · **Importance:** 9/10 · The primary, always-on data source.

## Summary

An adapter that pulls cheapest-fare-per-day data from the Travelpayouts / Aviasales Data
API and emits canonical `calendar_cheapest` fare observations.

## Depends on

- SF-03 (schema + store interfaces).
- L0 §5 adapter contract.
- A free Travelpayouts affiliate account + API token (manual, one-time; document the steps
  in the adapter README). Token via env `TRAVELPAYOUTS_TOKEN`.

## Files owned

```
pipeline/adapters/travelpayouts/**
tests/adapters/travelpayouts/**
```

## Source facts (from research — verify against live docs when building)

- Free: affiliate model, no per-call charge. Rate limit ~300 RPM on the price-calendar endpoint.
- Endpoint of interest: month price calendar — cheapest non-stop / 1-stop / 2-stop fare per
  day for a route, for a given month.
- Data is **cached** from real Aviasales searches, retained ~7 days. Prices are not live.
- Currency is a request parameter — request `USD`, store as-is.

## Behavior

- Implements the L0 §5 entry point: fetch request → fetch result.
- For a request spanning a date window, call the month-calendar endpoint for each month the
  window touches; filter to the requested `depart_date_from..to`.
- For each returned day/price, emit one canonical record:
  - `source = "travelpayouts"`, `price_kind = "calendar_cheapest"`.
  - `amount_minor` from the price (× 100 for USD), `currency = "USD"`.
  - `stops_outbound` set only if the response distinguishes it (e.g. the non-stop figure);
    otherwise null.
  - `carrier_primary` null unless the response includes it.
  - `observed_price_age_seconds` from the response's cache metadata if present, else null.
  - `fetched_at = now (UTC)`, `ingest_run_id` from the request.
- **One-way only** (L0 §8). If a request arrives with `trip_type = "round_trip"`, return
  `outcome = "empty"` with an `error_detail` saying round trips aren't supported yet. Do
  not attempt to synthesize a round-trip price. (A `return_date`-capable endpoint check is
  a task for when the MVP's one-way constraint is revisited.)
- Map failures to outcomes: HTTP 429 → `rate_limited` (+ `retry_after_seconds` from header
  if given); 5xx / network → `source_error`; 200 with no data → `empty`; got some months
  but hit a limit → `partial`.
- Rate limiting inside the adapter: token-bucket well under 300 RPM (default 60 RPM), with
  jitter. Configurable via env.
- Count every upstream HTTP call in `source_request_count`.

## Done when

- Against a recorded/mocked API response fixture, the adapter emits schema-valid canonical
  records with correct field mapping (unit-tested, no network).
- A live smoke test (guarded by the token env var) fetches one real route-month and
  produces valid records.
- 429 and 5xx responses produce the correct `outcome` and never raise.
- Re-running the same fetch on the same UTC day produces identical `observation_id`s
  (natural key uses `fetched_date`, not `fetched_at` — L0 §6).
- Round-trip requests return `outcome = "empty"` (never raise, never guess).
- Adapter README documents: how to get a token, the endpoints used, rate-limit defaults,
  and the one-way-only limitation.

## Out of scope

- Deciding *which* routes/dates to fetch (SF-04).
- Writing to the store (the scheduler does that).
- Quality checks (SF-05).
