# Decision 0001 — Tech Stack

**Date:** 2026-09-09
**Status:** accepted (backend); frontend deliberately deferred
**Resolves:** L0 §8 open decisions D1, D2, D4, D5, D6, and the backend half of D7

---

## Context

Specs are written stack-neutral. Nothing can be built until the stack is locked, because
parallel agents would otherwise produce incompatible code. Current focus is the **data
pipeline and prediction backend** — the website is explicitly out of scope for now.

## Decisions

### Backend — locked

| Area | Choice | Notes |
|------|--------|-------|
| **Language** (pipeline, models, API) | **Python** (3.12+) | Forced by `fast-flights` (Python-only) and the ML ecosystem (polars/pandas, scikit-learn, LightGBM, SHAP). The heavy compute runs in the C++/Rust internals of those libraries, so raw Python speed is not a concern. Rust/C++ considered and rejected — no bottleneck it would fix, large time cost, off-story for the portfolio. |
| **API framework** | **FastAPI** | Pydantic models double as the canonical schema layer (L0 §3); auto-generates the OpenAPI doc SF-07 needs. |
| **Storage — snapshot store** | **Parquet files + DuckDB** | No server, $0, SQL over Parquet, columnar scans suit the feature builders and backtest. Confirms the assumption already baked into L0 §1/§6/§7. |
| **Storage — operational state** | **SQLite** | Small mutable state only (scheduler bookkeeping now; accounts later). Not for fare data. |
| **Orchestration** | **cron + a Python entrypoint** | Daily cadence needs nothing heavier. Revisit (Prefect/Dagster) only if it becomes painful. |
| **Python tooling** | **`uv`** | One fast tool for venv + dependency resolution + lockfile. |
| **Backend hosting** | **Oracle Cloud Always Free (ARM VM)** | Genuinely free with no time limit; runs the cron collectors and the API. Keep infra reproducible in code — Oracle can reclaim idle instances. |

### Frontend — deferred, not decided

The website is **not being designed or built yet**. When it is, the owner will design it
himself using Claude Design, with a deliberately non-trivial technical build (explicitly to
avoid looking AI-generated / vibe-coded). Framework, language, and hosting for the frontend
are **open** and will get their own decision record then.

For now:
- **SF-08 (buy-vs-wait UI) is deferred.** See E2.
- The backend milestone ends at **SF-07** — the API returns correct JSON. That is the
  "done" line for the current phase.
- If a throwaway page is ever needed to eyeball the API output, it's a scratch tool, not
  the real frontend, and doesn't constrain the later decision.

### Auth (D8) — deferred

No accounts in the current phase. Decision deferred to E5.

## Consequences

- `pipeline/`, `models/`, `api/` are all one Python project sharing one `uv` environment.
- `web/` stays empty for now.
- The canonical schema lives in `pipeline/schema/` as Pydantic models — single source of truth.
- Current build order (see specs/README): SF-03 → {SF-01, SF-02, SF-05} → SF-04 → SF-06 → SF-07.
