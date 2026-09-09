# L3 — Build Specs

**Status:** binding for the current pass. These are the specs an implementing agent executes
line by line.

This folder is one tier below the subfeature specs. It does not add scope, change scope, or
restate contracts — it turns each in-scope subfeature into a file tree, a set of signatures,
a config file with committed defaults, a test list, and a commit sequence.

---

## How this tier relates to L0 / L1 / L2

| Tier | Where | Answers |
|------|-------|---------|
| **L0** | `specs/L0-foundation.md` | *What are the shared contracts?* Schema, natural key, store layout, repo layout, naming. Binding on everything. |
| **L1** | `specs/epics/E*.md` | *Why does this exist and what is out of scope?* |
| **L2** | `specs/subfeatures/SF-*.md` | *What must be true when this unit is done?* Files owned, behaviour, Done when. |
| **L3** | `specs/implementation/*-build.md` | *Exactly what do I type?* Every path, every signature, every config value, every test, in commit order. |

Reading order for an implementer: **L0 in full → the parent epic → the L2 subfeature → the
L3 build spec.** The L3 spec is the last word on *how*; the L2 spec is still the last word on
*what counts as done*, which is why every build spec carries a table mapping its tests back
to the parent's **Done when** bullets.

**Rules this tier follows.**

- Reuse, don't restate. L0 sections are referenced by number. A contract is copied only where
  L3 is *pinning* something L0 or L2 deliberately left abstract — the `observation_id`
  canonicalisation, the `read_frame()` dtypes, the percentile direction, the curve's
  day range.
- Same section pattern as L2: *Files owned* / *Depends on* / *Done when* / *Out of scope*.
- No prose that can't be verified. Every claim is either a path, a signature, a literal
  value, or a test name.
- Nothing here silently resolves a contradiction between existing specs. Where two specs
  disagree, the build spec points at the numbered open question below.

---

## What this pass builds

The full vertical slice **SF-03 → SF-06 → SF-07**, solo and sequential on `main`, no
worktree lanes. The ingestion subfeatures (SF-01, SF-02, SF-04, SF-05) are **skipped**; the
committed fixture dataset stands in for collected fares. MVP is one-way, economy, 1
passenger (L0 §8). Everything runs in CI against the fixture dataset with no network.

The two-lane split in `specs/README.md` describes a different, parallel pass. It does not
apply here — there is one agent, one branch.

## Execution order

| # | Spec | Produces | Blocks |
|---|------|----------|--------|
| 1 | [`P0-scaffold.md`](P0-scaffold.md) | `uv` project, L0 §1 tree, ruff + pytest, CI workflow | everything |
| 2 | [`SF-03-build.md`](SF-03-build.md) | `pipeline/schema/`, `pipeline/store/`, `shared/settings.py`, the committed fixture dataset | SF-06, SF-07 |
| 3 | [`SF-06-build.md`](SF-06-build.md) | `models/features/`, `models/baseline/`, `models/backtest/`, `config/baseline.yaml` | SF-07 |
| 4 | [`SF-07-build.md`](SF-07-build.md) | `api/`, `shared/routes.py`, `config/api.yaml`, `api/openapi.json` | — (phase finish line) |

Strictly sequential. Each spec's **Interfaces frozen for downstream** section is the contract
the next one is written against; do not start a spec until its predecessor is on `main` with
CI green.

Not built in this pass, and therefore absent from the tree: `pipeline/adapters/`,
`pipeline/quality/`, `pipeline/scheduler/`, `config/routes.yaml`, `config/quality.yaml`,
`web/`.

## Commit and PR rhythm

- Work directly on `main`. No worktree lanes: one agent, no concurrent writers, nothing to
  isolate from.
- Each build spec ends with an **Ordered commit plan** of 5–9 commits. Follow it in order.
  Commit and push after each — not one batch at the end.
- Commit messages are human-sounding, imperative, one line, no file listings, no AI
  attribution.
- Push before starting the next commit in the plan. `main` should never sit with
  uncommitted work.
- CI must be green before starting the next build spec. A red `main` blocks the slice.
- If a build spec turns out to be wrong mid-implementation, fix the spec in its own commit
  first, then implement. The specs stay the record of what was built.

Total: roughly 31 commits across the four specs.

## Stack, as applied here

Locked by `specs/decisions/0001-stack.md`: Python 3.12+, `uv`, FastAPI, Pydantic v2,
Parquet + DuckDB, pytest, ruff.

One choice decision 0001 left to the implementer: **polars, not pandas**, for every
dataframe path. It is Arrow-native so a DuckDB result crosses into a frame with no copy, it
has no index semantics to leak into the frozen `read_frame()` contract, and its dtypes are
strict enough that the contract is assertable in a test. pandas is not a dependency.

---

## Open questions for the owner

Five, all genuinely blocking or genuinely contradictory. Each has a recommended resolution;
the build specs are written **assuming the recommendation** and say so at the point of use.
If you decide differently, the named build spec section is what changes.

### 1. SF-07's example payload contradicts SF-06's verdict rule

`specs/subfeatures/SF-07-inference-api.md` shows a response with
`"price_percentile": 34` and `"verdict": "wait"`. SF-06's rule is
`wait` ⟸ `price_percentile >= 60`. At 34 the verdict must be `neutral`.

The wrong field is the **verdict**, not the percentile: the same example's `reason` says
"cheaper than 66% of the last year", which is exactly percentile 34 under the
low-means-cheap convention both specs otherwise use. So the example is internally consistent
except for that one word.

**Recommended:** treat SF-06's rule as authoritative and correct the SF-07 example to
`"verdict": "neutral"` — or, if the example's *shape* is what you wanted to illustrate,
change its `price_percentile` to `72`. Do not loosen the `wait` threshold to fit the example;
a `wait` at percentile 34 tells a user to gamble on a fare that is already in the cheapest
third of its history.
*Affects:* `SF-07-build.md` §9 contract tests. Built assuming the rule, not the example.

### 2. "The last year" is a claim the fixture cannot support

SF-06 defines the percentile over "the trailing year"; SF-07's example `basis` reads
`"from": "2025-09-01", "to": "2026-09-08"` and its `reason` says "cheaper than 66% of the
last year". The committed fixture holds **90 fetched dates** (2026-06-12 … 2026-09-09), and
will hold roughly that much real history for the first three months of collection too. An API
that says "the last year" over 90 days of data is making a claim it cannot back — which is
the one thing E2's "every number is traceable to the snapshot store" rule forbids.

**Recommended:** keep `history.window_days: 365` as the *window we look in*, but build the
`reason` string from `basis.observations` and `basis.from_`/`basis.to` — "cheaper than 66% of
the 1,350 observations we have for JFK-LHR booked 31-45 days out" — never from a hardcoded
period. Update SF-07's example `basis` to a range the fixture can produce.
*Affects:* `SF-06-build.md` §4.4 `build_reason()`. Built assuming this.

### 3. `GET /routes` needs a route set that SF-04 owns and this pass does not build

SF-07's `GET /routes` returns "the configured route set". The configured route set is
`config/routes.yaml`, which L0 §1 and SF-04 assign to **SF-04** — skipped this pass, so the
file will not exist. `data/fixtures/routes.csv` exists (SF-03) but L0 §1 calls it the *test
mirror*, and SF-04 explicitly marks it read-only for everyone else.

**Recommended:** add `shared/routes.py` — a loader that reads the first path that exists from
an ordered list, `config/routes.yaml` then `data/fixtures/routes.csv`, and returns the same
`Route` object either way. This is L0 §1's own rule ("if two subfeatures would need the same
file, that file belongs in `shared/`"), it reads `routes.csv` without modifying it, and when
SF-04 later ships `config/routes.yaml` the API picks it up with no code change. The
alternative — having SF-03 create a starter `config/routes.yaml` — takes a file out of SF-04's
ownership and would need L0 §1 amended first.
*Affects:* `SF-07-build.md` §3 and §2 (`config/api.yaml routes.source_order`). Built assuming
the loader.

### 4. `config/baseline.yaml` is required by SF-06 but is not in its *Files owned*

SF-06's body says "defaults, config in `config/baseline.yaml`" and its Done-when requires
"all thresholds are config-driven", but its *Files owned* block lists only `models/**`,
`tests/models/**`. No spec owns the file, so nobody creates it.

**Recommended:** assign `config/baseline.yaml` to SF-06 and add it to that spec's *Files
owned*. The same gap exists for the API's serving settings; those go in `config/api.yaml`
under SF-07. Neither file is contested — SF-04's `config/routes.yaml` and SF-05's
`config/quality.yaml` stay untouched.
*Affects:* `SF-06-build.md` §2, `SF-07-build.md` §2. Built assuming the assignment.

### 5. Error-fare depth is specified against a different baseline than the gate that must catch it

SF-03 asks for outliers "70–85% below the **expected price** for their cell", and adds
"deep enough to trip SF-05's `price_below_floor` gate (floor is 0.35× the trailing median)".
Those are two different denominators. The expected price for a cell carries the seasonal, DOW
and advance-purchase multipliers; the floor is computed against the **median over a whole
(route, AP bucket)**, which averages those away. A cell whose expected price is already 25%
below its bucket median can be 85% below *expected* and still sit above 0.35× the *median*.
As written, the two requirements are not guaranteed to be satisfiable together.

**Recommended:** define the injection against the quantity the gate uses — overwrite the 12
chosen cells with `0.22 × median(amount_minor)` for their `(route, AP bucket)`. `0.22 < 0.35`
makes the gate fire by construction, and on the committed price model the realised depth
lands at 72–83% below expected, inside SF-03's stated band. The generator records the
realised per-outlier depth in `data/fixtures/README.md` so the claim is checkable rather
than asserted.
*Affects:* `SF-03-build.md` §4.4. Built assuming the median-relative injection.

---

### Pinned without asking

These were ambiguous but not contradictory, so the build specs resolve them inline with a
one-line rationale rather than sending them back:

the `days_to_departure` grid reading of L0 §7's fixture arithmetic (`SF-03-build.md` §4.1);
`observation_id` field encoding and the five fixed vectors (§2.3); the pinned Arrow types and
timestamp unit (§2.5); the `ingest_run_id` dedup tiebreaker (§2.8); all fixture rows carrying
`data_quality = "ok"` because SF-05 owns stamping (§4.3); single-currency fixtures (§4.3);
percentile direction and mid-rank ties (`SF-06-build.md` §4.2); the curve's day range and
that month/DOW are fixed by `depart_date` (§4.3); backtest hit/regret definitions (§5);
`400` for out-of-MVP cabin and passenger counts (`SF-07-build.md` §6); the `/predict` cache
key including the as-of date (§7); and `polars` over pandas (above).

### Follow-up, not blocking

`specs/README.md`'s tiering table lists L0 / L1 / L2. Adding an L3 row pointing at this
folder would keep that table complete. Left alone here because this pass was scoped to five
files.
