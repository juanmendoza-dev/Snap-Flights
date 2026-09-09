# E6 — Booking Handoff

**Status:** STUB. Not specced in depth yet.
**Depends on:** E2 (a searched/priced trip to hand off), E1 adapters (source of the deep link).

## Goal

Get the user to the cheapest place to actually book, and tell them how trustworthy that
place is. Snap Flights does not sell tickets — it hands off.

## Candidate subfeatures (importance)

| Feature | Rating |
|---------|--------|
| Deep links to cheapest source + OTA reliability rating | 8 |
| True final price including payment-method fees | 7 |
| OTA trustworthiness score (support quality, hidden fees, cancellation pain) | 6 |
| Itinerary import + monitoring from any source | 5 |
| Best credit card for the purchase (points, insurance) | 4 |
| Schedule-change / disruption assistant | 4 |
| Auto check-in | 3 |

## Scope boundary

- Travelpayouts is an affiliate network — deep links there also cover the revenue model.
  That connection is worth designing deliberately when this is specced.
- OTA trustworthiness score needs a data source (reviews, complaint data) — TBD, likely
  a curated static dataset to start, not scraped.
- The earlier draft rated a full booking/checkout flow 2/10 and out of scope. Still true —
  this epic is handoff only.

## Not specced yet — do not implement.
