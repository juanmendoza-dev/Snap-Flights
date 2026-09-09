# E7 — Trip Quality

**Status:** STUB. Not specced in depth yet.
**Depends on:** E1 for the route set; a *separate* data path for flight status/position data
(OpenSky or similar) — this does NOT flow through the fare-observation schema.

## Goal

Make sure "cheapest" isn't "miserable". Score the non-price quality of an itinerary so the
buy-vs-wait screen can warn about a bad connection or a chronically delayed flight.

## Candidate subfeatures (importance)

| Feature | Rating |
|---------|--------|
| Layover risk score (missed-connection probability from historical data) | 7 |
| On-time / cancellation rate per flight number | 6 |
| Aircraft / seat / wifi / legroom / power data | 5 |
| "Worth the upgrade?" analysis | 5 |
| Total door-to-door time including airport transit | 5 |
| Carbon footprint with cheaper + greener alternatives | 5 |
| Delay/disruption compensation estimator (EU261 etc.) | 4 |
| Red-eye / arrival-time quality scoring | 4 |

## Scope boundary

- New data domain: flight status, historical on-time performance, positions. Free sources
  exist (OpenSky is free, 4000 credits/day) but they are *tracking*, not pricing.
- This gets its own adapter path and its own store — do not extend the fare schema.
- Seat/aircraft data is largely static reference data; source TBD (was SeatGuru-style).

## Not specced yet — do not implement.
