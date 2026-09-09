# SF-04 — Collection Scheduler + Route Prioritization

**Epic:** E1 · **Importance:** 8/10 · The thing that actually runs the pipeline daily.

## Summary

Decide what to fetch each run, call the adapters, run results through the quality gates,
write to the snapshot store, and re-queue partial/failed work. Owns route tiers and cadence.

## Depends on

- SF-03 (store), SF-05 (quality gates), and at least one of SF-01 / SF-02.
- Open decision **D5** (cron vs. workflow engine) — but build the run logic as a plain
  callable first so it works under either.

## Files owned

```
pipeline/scheduler/**
config/routes.yaml              # production route set + tiers — OWNED here
tests/scheduler/**
```

**Read-only, do not modify:** `data/fixtures/routes.csv` (SF-03 owns it; column schema
pinned in L0 §1). If the scheduler needs a new route attribute, add it to `config/routes.yaml`
only; a matching column in `routes.csv` must be pinned in L0 §1 first.

## Concepts

### Route tiers & cadence

| Tier | Meaning | Fetch cadence | Departure-date horizon |
|------|---------|---------------|------------------------|
| 1 | hot routes (featured, high search volume) | daily | next 180 days |
| 2 | warm | every 3 days | next 120 days |
| 3 | cold (coverage only) | weekly | next 90 days |

Numbers are defaults; live in `config/routes.yaml`.

### One collection run

1. Generate a new `ingest_run_id` (uuid).
2. From the route config + last-fetched bookkeeping, build the list of
   `(route, depart_date_window, trip_type, cabin)` fetch requests due this run.
   MVP: `trip_type` is always `one_way`, `cabin` always `economy` (L0 §8).
3. Respect per-adapter budgets: Travelpayouts first (cheap, broad); fast-flights only for
   tier-1 routes and only within its daily cap (SF-02).
4. For each request: call the adapter → take `records` → pass through SF-05 gates →
   `store.write(gated_records)`.
5. Handle outcomes:
   - `partial` / `rate_limited` → re-queue the uncovered window for the next run (persist a
     small work-queue file under `data/snapshots/_scheduler/`).
   - `blocked` (fast-flights) → skip that adapter for the rest of the run.
   - `source_error` → log, count, continue.
6. Write a run summary (records written per source, outcomes, request counts, gate rejections)
   to `data/snapshots/_scheduler/runs/{ingest_run_id}.json`.
7. If the run summary trips a run-level alarm from SF-05 (e.g. zero records, all-suspect),
   exit non-zero.

## Done when

- One command executes a full run against the real adapters and appends gated records with
  a shared `ingest_run_id`.
- The same command runs in CI against a mock adapter with no network and writes to a temp store.
- A simulated `partial` outcome results in the gap being re-queued and picked up next run.
- Tier cadence is respected: a tier-2 route fetched today is not re-fetched tomorrow.
- fast-flights is never called beyond its daily cap or for non-tier-1 routes.
- Run summary JSON is written every run and a zero-record run exits non-zero.

## Out of scope

- The adapters themselves, the schema, the gates.
- Watchlist evaluation (E5 — different scheduler).
- A hosted scheduler deployment (ops task, after D5/D7).
