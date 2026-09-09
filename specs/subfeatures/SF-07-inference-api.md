# SF-07 — Inference API

**Epic:** E2 · **Importance:** 9/10 · How the frontend (and later, alerts) gets predictions.

## Summary

An HTTP API that takes a trip shape, gets current price context + a prediction from the
baseline model, and returns a single JSON payload the UI can render directly.

## Depends on

- SF-06 (the model + feature builders).
- SF-03 (store).
- Stack (decision 0001): **Python + FastAPI**. Reuse the Pydantic schema models from `pipeline/schema/` for request/response types. Commit the generated OpenAPI doc.

## Files owned

```
api/**
tests/api/**
```

## Endpoints (MVP)

### `GET /health`
Liveness + which data sources have recent observations + fixture-mode flag.

### `POST /predict`

Request:
```json
{
  "origin": "JFK", "destination": "LHR",
  "depart_date": "2026-12-20",
  "trip_type": "one_way", "cabin": "economy", "passengers": 1,
  "current_price": { "amount_minor": 42900, "currency": "USD" }
}
```
MVP is **one-way only** (L0 §8): `trip_type` must be `one_way`, `return_date` must be
absent. A round-trip request gets `400` with a clear message.
`current_price` optional — if omitted, the API uses the latest observed cheapest for the
trip shape from the store.

Response:
```json
{
  "trip_shape": { ...echoed... },
  "current_price": { "amount_minor": 42900, "currency": "USD", "source": "user_supplied|store", "as_of": "2026-09-09T14:00:00Z" },
  "price_percentile": 34,
  "verdict": "wait",
  "expected_low": { "amount_minor": 38000, "currency": "USD", "window_start": "2026-09-20", "window_end": "2026-10-04" },
  "expected_curve": [ { "days_to_departure": 90, "amount_minor": 41000 }, ... ],
  "confidence": "medium",
  "reason": "This fare is cheaper than 66% of the last year, but prices on this route usually dip about 10% around 10-11 weeks out.",
  "basis": { "observations": 412, "from": "2025-09-01", "to": "2026-09-08", "sources": ["travelpayouts", "fastflights"] },
  "data_quality_note": null
}
```

### `GET /routes`
The configured route set + which have enough history for a `high`/`medium` confidence answer.

## Behavior

- Validate the request against the canonical enums/formats from L0 §2.
- Unknown route or route with < minimum history → `200` with `verdict: "neutral"`,
  `confidence: "low"`, and a `data_quality_note` explaining the thin data (never a 500).
- Cache identical `/predict` requests briefly (default 6h — matches collection cadence).
- Read-only. No writes, no auth (MVP). CORS open to the `web/` origin.
- Response time target < 300 ms warm on the fixture dataset.

## Done when

- `POST /predict` returns the full payload for every fixture route, with and without `current_price`.
- Thin-data and unknown-route cases return `200` with the documented shape.
- Contract tests pin the response schema, and the OpenAPI doc is committed (so the frontend can build against it later — SF-08 is deferred).
- Runs in CI against the fixture dataset with no network.
- OpenAPI/schema doc generated or committed for the frontend.

## Out of scope

- Search across many routes/dates (E3).
- Auth, rate limiting per user, accounts (E5 / open decision D8).
- Serving the trained model (Phase 2).
