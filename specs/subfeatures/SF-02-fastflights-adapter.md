# SF-02 — fast-flights Source Adapter

**Epic:** E1 · **Importance:** 8/10 · Live ground-truth reference. Used sparingly.

## Summary

An adapter wrapping the open-source `fast-flights` library (reconstructs Google Flights'
protobuf endpoint) to emit canonical `itinerary` fare observations for a small set of
priority routes/dates.

## Depends on

- SF-03.
- L0 §5 adapter contract.
- The `fast-flights` library (`AWeirdDev/flights` on GitHub) as a dependency — pin a version.

## Files owned

```
pipeline/adapters/fastflights/**
tests/adapters/fastflights/**
```

## Source facts

- Free, no API key. Not an official API — it mimics Google Flights' internal request.
- **Fragile:** breaks when Google changes their format. Treat every call as able to fail.
- ToS-gray: keep request volume low, pace requests, expect the need for IP variation.
- Returns specific itineraries: price, stops, carriers, duration, sometimes emissions.

## Behavior

- Implements the L0 §5 entry point.
- **Conservative by design:** default max ~200 fetches/day across all routes, hard-capped in
  the adapter, configurable via env. Long delay + jitter between calls (default 5–15s).
- For a fetch request, query the library for that O&D + date(s) + cabin, take the cheapest
  N (default 3) itineraries, emit one canonical record each:
  - `source = "fastflights"`, `price_kind = "itinerary"`.
  - `stops_outbound` / `stops_return`, `carrier_primary` (first marketing carrier) filled.
  - `amount_minor` + `currency` from the result (request USD).
  - `source_native_id` = a stable hash of the itinerary legs if the library exposes enough detail.
- Failure mapping: library exception / parse failure / empty → `source_error` with
  `error_detail` (do NOT raise); obvious bot-block / captcha signal → `blocked`;
  zero itineraries but a clean response → `empty`; hit the daily cap mid-request → `partial`.
- On three consecutive `source_error`/`blocked` outcomes, the adapter sets a cooldown
  (default 6h) and returns `blocked` immediately for further requests until it passes.

## Done when

- Against a recorded library response, emits schema-valid `itinerary` records with correct
  mapping (unit-tested, no network).
- A guarded live smoke test fetches one real route and produces valid records.
- Library exceptions produce `source_error` and never propagate.
- Daily cap and cooldown behavior are unit-tested with a fake clock.
- Round-trip requests return `outcome = "empty"` (MVP is one-way — L0 §8).
- Re-running the same fetch on the same UTC day produces identical `observation_id`s.
- Adapter README documents the fragility, the caps, the cooldown, and how to bump the
  pinned library version.

## Out of scope

- Route/date selection (SF-04) — but SF-04 must respect this adapter's daily cap.
- Store writes, quality checks.
- Proxy/IP-rotation infrastructure (note it as a future need; not built now).
