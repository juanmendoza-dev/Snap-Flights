# E4 — Cheap-Fare Hunting

**Status:** STUB. Not specced in depth yet.
**Depends on:** E1 (fare history), and a routing/pricing engine that doesn't exist yet.

## Goal

Surface the fares Google Flights won't show you — the "cheaper than anywhere else" half of
the product pitch. Most of these share one underlying **fare-construction / routing engine**;
that engine should be the first subfeature when this epic is specced.

## Candidate subfeatures (importance)

| Feature | Rating |
|---------|--------|
| Hidden-city / skiplagging finder (with risk warnings) | 9 |
| Split-ticket engine (two tickets beat one through-fare) | 8 |
| Nearby-airport + nearby-date matrix | 8 |
| Error / mistake fare detection | 8 |
| Bundled vs. unbundled true-cost calculator (bags, seat, carry-on) | 8 |
| Budget-airline coverage Google omits | 7 |
| Positioning-flight suggestions | 6 |
| Open-jaw / multi-city routing optimizer | 6 |
| Throwaway ticketing detection | 5 |
| Multi-currency / point-of-sale arbitrage | 5 |
| Stopover-as-free-trip finder | 5 |
| Repricing / cancel-and-rebook alerts after booking | 5 |
| Award vs. cash comparison | 4 |
| "Ghost" fare tracking | 4 |
| Fuel dump / fare construction | 2 |

## Scope boundary

- Error-fare *detection* logic overlaps with E1's quality gates (which flag statistical
  outliers). E4's version is user-facing and cross-source; decide the split when specced.
- Budget-airline coverage needs airline-direct adapters — an E1 addition — as a prerequisite.
- Every "trick" feature ships with a plain risk disclaimer (skiplagging violates airline
  terms, etc.). That copy is a shared component, specced once.

## Not specced yet — do not implement.
