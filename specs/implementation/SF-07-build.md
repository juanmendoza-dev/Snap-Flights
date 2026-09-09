# SF-07 — Build Spec: Inference API

**Tier:** L3 (build spec) · **Parent:** `specs/subfeatures/SF-07-inference-api.md`
**Execution slot:** fourth and last. This is the current-phase finish line (decision 0001).

## Summary

Implements SF-07 exactly: a FastAPI app with `GET /health`, `POST /predict` and
`GET /routes`, serving `models.baseline.predict()` over the fixture dataset, with a
committed OpenAPI document.

## Depends on

- SF-06 on `main`, and specifically the interfaces frozen in `SF-06-build.md` §8.
- SF-03's store + fixtures (`SF-03-build.md` §9).
- Decision 0001: Python + FastAPI, Pydantic v2 request/response models reusing
  `pipeline/schema/`.

## Files owned

```
api/__init__.py                  # (exists from P0) — re-exports create_app
api/app.py                       # create_app() factory, CORS, exception handlers, router wiring
api/settings.py                  # ApiSettings + load_api_settings() over config/api.yaml
api/models.py                    # request/response Pydantic models (the wire contract)
api/cache.py                     # TTL cache for /predict, clearable
api/dependencies.py              # FastAPI dependency providers: store, config, settings, cache
api/routers/__init__.py
api/routers/health.py            # GET /health
api/routers/predict.py           # POST /predict
api/routers/routes.py            # GET /routes
api/errors.py                    # ApiError + the RFC-shaped error body
api/openapi.json                 # COMMITTED generated OpenAPI document
shared/routes.py                 # route-set loader (config/routes.yaml if present, else fixtures)
config/api.yaml                  # OWNED HERE — cache TTL, CORS, health window, min history
scripts/dump_openapi.py          # regenerates api/openapi.json; --check for CI
tests/api/__init__.py
tests/api/conftest.py            # TestClient in fixture mode, cache cleared per test
tests/api/test_health.py
tests/api/test_predict.py
tests/api/test_predict_validation.py
tests/api/test_routes.py
tests/api/test_cache.py
tests/api/test_openapi.py
tests/api/test_contract.py       # pins the exact response shape from the SF-07 spec
```

**Not owned:** `models/**`, `pipeline/**`, `config/baseline.yaml`, `config/routes.yaml`,
`web/**` (SF-08 deferred).

**Note on `shared/routes.py`:** the route set is needed by `api/` now and by
`pipeline/scheduler/` later, which is L0 §1's own criterion for putting a file in `shared/`.
`config/routes.yaml` is SF-04's and does not exist in this pass, so the loader reads it when
present and falls back to `data/fixtures/routes.csv`. This adds nothing to SF-04's ownership.
See `specs/implementation/README.md` open question 3.

## 1. Exact file tree

The block above is the tree, one line per path, nothing else.

## 2. `config/api.yaml` — committed default

```yaml
# Inference API (SF-07). Serving settings only — model thresholds live in config/baseline.yaml.
schema_version: 1

cache:
  # SF-07: "cache identical /predict requests briefly (default 6h — matches collection cadence)".
  predict_ttl_seconds: 21600
  max_entries: 1024
  enabled: true

cors:
  # SF-07: "CORS open to the web/ origin". The frontend stack is deferred (D3), so these are
  # the conventional local dev origins; replace when D3 lands.
  allow_origins:
    - "http://localhost:3000"
    - "http://localhost:5173"
  allow_credentials: false
  allow_methods: ["GET", "POST", "OPTIONS"]
  allow_headers: ["*"]

health:
  # A source counts as "recent" if it has a fetched_date within this many days of today.
  recent_observation_window_days: 3

routes:
  # First path that exists wins. config/routes.yaml is SF-04's and absent in this pass.
  source_order:
    - "config/routes.yaml"
    - "data/fixtures/routes.csv"

serving:
  # Below this many observations in the (route, AP bucket) cell, GET /routes reports the
  # route as thin. Kept equal to config/baseline.yaml history.min_cell_observations;
  # a test asserts they agree so the API cannot disagree with the model.
  min_cell_observations: 30
  # Guard rail: a depart_date more than this far out is rejected with 400 rather than
  # producing a curve from an empty cell.
  max_days_to_departure: 365
```

```python
# api/settings.py
class CacheSettings(BaseModel): predict_ttl_seconds: int; max_entries: int; enabled: bool
class CorsSettings(BaseModel): allow_origins: list[str]; allow_credentials: bool; allow_methods: list[str]; allow_headers: list[str]
class HealthSettings(BaseModel): recent_observation_window_days: int
class RoutesSettings(BaseModel): source_order: list[str]
class ServingSettings(BaseModel): min_cell_observations: int; max_days_to_departure: int

class ApiSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: int
    cache: CacheSettings
    cors: CorsSettings
    health: HealthSettings
    routes: RoutesSettings
    serving: ServingSettings

DEFAULT_API_CONFIG_PATH: Path   # {repo_root}/config/api.yaml

def load_api_settings(path: Path | None = None) -> ApiSettings: ...
```

## 3. `shared/routes.py`

```python
@dataclass(frozen=True, slots=True)
class Route:
    """Columns pinned in L0 §1. Identical shape whether loaded from YAML or CSV."""
    route_key: str
    origin: str
    destination: str
    region: str
    tier: int

def load_routes(*, source_order: Sequence[str] | None = None,
                repo_root: Path | None = None) -> tuple[Route, ...]:
    """First existing path in source_order wins. `.yaml` is parsed as SF-04's route config
    (a `routes:` list of mappings); `.csv` as L0 §1's five columns. Sorted by route_key.
    Raises FileNotFoundError when no source exists — a route-less API is a deploy error,
    not a runtime condition to paper over."""

def route_index(routes: Iterable[Route]) -> dict[str, Route]: ...
```

## 4. Wire models — `api/models.py`

Canonical enums and constrained types are **imported** from `pipeline/schema/`, not
redeclared (SF-07: "reuse the Pydantic schema models from `pipeline/schema/`").

```python
from pipeline.schema import Cabin, PriceKind, Source, TripType
from pipeline.schema.record import CurrencyCode, IataCode
from models.baseline import Confidence, Verdict

class MoneyIn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    amount_minor: int = Field(gt=0)
    currency: CurrencyCode

class PredictRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    origin: IataCode
    destination: IataCode
    depart_date: date
    trip_type: TripType = TripType.ONE_WAY
    cabin: Cabin = Cabin.ECONOMY
    passengers: int = Field(default=1, ge=1)
    return_date: date | None = None
    current_price: MoneyIn | None = None

class TripShapeOut(BaseModel):
    origin: IataCode; destination: IataCode; route_key: str
    depart_date: date; return_date: date | None
    trip_type: TripType; cabin: Cabin; passengers: int

class CurrentPriceOut(BaseModel):
    amount_minor: int; currency: CurrencyCode
    source: Literal["user_supplied", "store"]
    as_of: datetime

class CurvePointOut(BaseModel):
    days_to_departure: int; amount_minor: int

class ExpectedLowOut(BaseModel):
    amount_minor: int; currency: CurrencyCode
    window_start: date; window_end: date

class BasisOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    observations: int
    from_: date = Field(alias="from")
    to: date = Field(alias="to")
    sources: list[str]

class PredictResponse(BaseModel):
    """Field order is the order of SF-07's documented payload; FastAPI preserves it."""
    trip_shape: TripShapeOut
    current_price: CurrentPriceOut
    price_percentile: int = Field(ge=0, le=100)
    verdict: Verdict
    expected_low: ExpectedLowOut | None
    expected_curve: list[CurvePointOut]
    confidence: Confidence
    reason: str
    basis: BasisOut
    data_quality_note: str | None = None

    @classmethod
    def from_prediction(cls, prediction: Prediction) -> "PredictResponse":
        """The ONLY mapping from models.baseline.Prediction to the wire. No recomputation,
        no rounding, no re-derivation — every value is copied. `basis` is narrowed to the
        four fields SF-07 documents; the extra Basis fields SF-06 carries (ap_bucket, cov,
        route_observations, travel_month, travel_dow) are intentionally not exposed."""

class HealthResponse(BaseModel):
    status: Literal["ok"]
    fixture_mode: bool
    schema_version: int
    sources: list[SourceHealth]
    routes_loaded: int
    checked_at: datetime

class SourceHealth(BaseModel):
    source: str
    last_fetched_date: date | None
    recent: bool                 # within health.recent_observation_window_days

class RouteSummary(BaseModel):
    route_key: str; origin: str; destination: str; region: str; tier: int
    observations: int            # rows in the trailing history window for this route
    first_fetched_date: date | None
    last_fetched_date: date | None
    max_confidence: Confidence   # best confidence any AP bucket on this route can reach
    has_sufficient_history: bool # >= serving.min_cell_observations in at least one bucket

class RoutesResponse(BaseModel):
    routes: list[RouteSummary]
    min_cell_observations: int
    as_of: date

class ErrorBody(BaseModel):
    """Every 4xx/5xx has this body. FastAPI's default {"detail": ...} is replaced so the
    frontend has one error shape to code against."""
    error: str          # machine code, e.g. "round_trip_not_supported"
    message: str        # human-readable
    field: str | None = None
```

## 5. Routes

```python
# api/app.py
def create_app(
    *,
    settings: ApiSettings | None = None,
    baseline_config: BaselineConfig | None = None,
    store: SnapshotStore | None = None,
) -> FastAPI:
    """App factory. Every collaborator is injectable so tests never touch globals.
    Adds CORSMiddleware from settings.cors, registers the three routers, installs the
    ApiError / RequestValidationError handlers that emit ErrorBody, and sets
    title='Snap Flights Inference API', version='0.1.0', openapi_url='/openapi.json'."""

app = create_app()   # module-level instance for `uvicorn api.app:app`
```

```python
# api/routers/health.py
@router.get("/health", response_model=HealthResponse, tags=["ops"])
def get_health(
    store: Annotated[SnapshotStore, Depends(get_store)],
    settings: Annotated[ApiSettings, Depends(get_api_settings)],
) -> HealthResponse:
    """Liveness + which sources have recent observations + the fixture-mode flag.
    fixture_mode reads shared.settings.use_fixtures() — the same accessor everything else
    uses (SF-03-build §9.6). Always 200 while the process is up; a store with no data is
    reported as sources=[] with routes_loaded from the route file, not an error."""
```

```python
# api/routers/predict.py
@router.post("/predict", response_model=PredictResponse, tags=["prediction"],
             responses={400: {"model": ErrorBody}})
def post_predict(
    request: PredictRequest,
    store: Annotated[SnapshotStore, Depends(get_store)],
    baseline_config: Annotated[BaselineConfig, Depends(get_baseline_config)],
    settings: Annotated[ApiSettings, Depends(get_api_settings)],
    cache: Annotated[PredictCache, Depends(get_predict_cache)],
) -> PredictResponse:
    """1. Reject out-of-MVP requests with 400 (§6).
       2. Build models.baseline.TripShape and an optional Money.
       3. Cache lookup on the key in §7.
       4. models.baseline.predict(trip_shape, current_price, as_of=today_utc,
          config=baseline_config, store=store).
       5. PredictResponse.from_prediction(...), cache it, return it.
       Thin data and unknown routes are 200 — predict() already returns the neutral/low/
       note shape (SF-06-build §8.7); this router does not special-case them."""
```

```python
# api/routers/routes.py
@router.get("/routes", response_model=RoutesResponse, tags=["reference"])
def get_routes(
    store: Annotated[SnapshotStore, Depends(get_store)],
    baseline_config: Annotated[BaselineConfig, Depends(get_baseline_config)],
    settings: Annotated[ApiSettings, Depends(get_api_settings)],
) -> RoutesResponse:
    """The configured route set (shared.routes.load_routes) joined with per-route history
    counts from a single store.read_frame() over the trailing history window, grouped by
    (route_key, ap_bucket). max_confidence is decide_confidence() applied to the best
    bucket. One store read for all routes — not one per route."""
```

## 6. Request validation — the 400 rules, pinned

| Condition | HTTP | `error` | `message` |
|---|---|---|---|
| `trip_type != "one_way"` | 400 | `round_trip_not_supported` | `The MVP supports one-way trips only.` |
| `return_date` present | 400 | `return_date_not_supported` | `The MVP supports one-way trips only; omit return_date.` |
| `cabin != "economy"` | 400 | `cabin_not_supported` | `The MVP supports economy only.` |
| `passengers != 1` | 400 | `passengers_not_supported` | `The MVP supports 1 passenger only.` |
| `origin == destination` | 400 | `same_origin_destination` | `Origin and destination must differ.` |
| `depart_date` before today (UTC) | 400 | `depart_date_in_the_past` | `depart_date must be today or later.` |
| `depart_date` more than `serving.max_days_to_departure` out | 400 | `depart_date_too_far` | `depart_date must be within {n} days.` |
| Malformed IATA / currency / date, unknown enum value, unknown field | 422 | `validation_error` | Pydantic's message, `field` set |

L0 §8 fixes the MVP at one-way / economy / 1 passenger, and SF-07 spells out only the
round-trip 400. Rejecting the other two out-of-MVP values the same way is the consistent
reading: the model has no non-economy or multi-passenger history to answer from, so a 200
would be a fabricated answer. An **unknown route** is explicitly *not* a 400 — SF-07 requires
a 200 with `verdict: "neutral"`.

FastAPI's own `RequestValidationError` produces 422; the MVP-scope checks above run in the
router and produce 400. Both are rendered as `ErrorBody`.

## 7. `api/cache.py`

```python
class PredictCache:
    """In-process TTL cache. No Redis, no shared state — the MVP runs one process.

    Key (pinned): (origin, destination, depart_date.isoformat(), trip_type, cabin,
                   passengers, current_price.amount_minor or -1,
                   current_price.currency or "", as_of_date.isoformat())

    as_of_date is in the key so a cached entry cannot survive a date rollover and answer
    with yesterday's days-to-departure.
    """

    def __init__(self, *, ttl_seconds: int, max_entries: int, enabled: bool = True,
                 clock: Callable[[], float] = time.monotonic) -> None: ...

    def get(self, key: tuple[object, ...]) -> PredictResponse | None: ...
    def set(self, key: tuple[object, ...], value: PredictResponse) -> None: ...
    def clear(self) -> None: ...

    @property
    def size(self) -> int: ...
```

- `enabled=False` (or `ttl_seconds <= 0`) makes `get()` always miss and `set()` a no-op.
- Eviction is insertion-ordered (oldest first) once `max_entries` is reached.
- `clock` is injectable so TTL expiry is tested without sleeping.
- `tests/api/conftest.py` calls `cache.clear()` in an autouse fixture. Without it the
  contract tests pollute each other and a failure in one shows up in another.

## 8. `api/openapi.json` and `scripts/dump_openapi.py`

SF-07 requires the OpenAPI document committed so the deferred frontend can build against it.

```python
def main(argv: list[str] | None = None) -> int:
    """--out PATH (default api/openapi.json)
       --check   regenerate in memory and compare; exit 1 with a diff hint on mismatch."""
```

Written with `json.dumps(..., indent=2, sort_keys=True, ensure_ascii=False)` + a trailing
newline so the file diffs cleanly. `tests/api/test_openapi.py::test_committed_doc_is_current`
runs the `--check` path, which keeps the committed document honest without adding a CI step
to P0's workflow.

## 9. Test list — mapped to SF-07's Done when

| SF-07 "Done when" bullet | Test |
|---|---|
| `POST /predict` returns the full payload for every fixture route, with and without `current_price` | `tests/api/test_predict.py::test_all_fixture_routes_with_current_price` (parametrised over the 15 route keys), `::test_all_fixture_routes_without_current_price`, `::test_current_price_source_is_user_supplied_when_given`, `::test_current_price_source_is_store_when_omitted`, `::test_response_matches_predict_output` (asserts every field equals `models.baseline.predict()` called directly — no recomputation in `api/`) |
| Thin-data and unknown-route cases return `200` with the documented shape | `tests/api/test_predict.py::test_unknown_route_returns_200_neutral_low`, `::test_unknown_route_has_data_quality_note`, `::test_thin_history_returns_200_neutral_low`, `::test_thin_data_response_still_validates_against_the_contract` |
| Contract tests pin the response schema | `tests/api/test_contract.py::test_predict_response_keys_exact` (the 10 top-level keys of SF-07's payload, in order), `::test_basis_serialises_from_not_from_underscore`, `::test_expected_low_null_unless_wait`, `::test_expected_curve_descending_from_dtd_now`, `::test_price_percentile_is_int_0_100`, `::test_verdict_and_confidence_enum_values`, `::test_error_body_shape_on_400`, `::test_error_body_shape_on_422` |
| … and the OpenAPI doc is committed | `tests/api/test_openapi.py::test_committed_doc_is_current`, `::test_doc_contains_the_three_paths`, `::test_predict_400_documented`, `::test_doc_is_sorted_and_indented` |
| Runs in CI against the fixture dataset with no network | `tests/api/conftest.py` sets `SNAP_USE_FIXTURES=1` and asserts `data/snapshots/` is absent; `tests/api/test_health.py::test_fixture_mode_flag_is_true`, `tests/api/test_predict.py::test_no_outbound_socket` (monkeypatches `socket.socket` to raise for the duration of a `/predict` call; if DuckDB or pyarrow turn out to open a local socket internally, drop this test and rely on CI running with no egress instead of weakening it) |
| OpenAPI/schema doc generated or committed for the frontend | same as above — `api/openapi.json` is a committed file |

Supporting tests:

| Test | Asserts |
|---|---|
| `test_health.py::test_status_ok` | 200, `status == "ok"` |
| `test_health.py::test_sources_reported` | both fixture sources present, `last_fetched_date == 2026-09-09` |
| `test_health.py::test_recent_flag_uses_configured_window` | |
| `test_health.py::test_routes_loaded_is_15` | |
| `test_predict_validation.py` | one test per row of the §6 table, asserting status, `error` code and `message` |
| `test_predict_validation.py::test_unknown_field_is_422` | `extra="forbid"` is live on the wire |
| `test_predict_validation.py::test_lowercase_iata_is_422` | L0 §2 formats enforced |
| `test_routes.py::test_returns_all_15_routes` | joined with `data/fixtures/routes.csv` |
| `test_routes.py::test_route_metadata_matches_csv` | region and tier round-trip |
| `test_routes.py::test_max_confidence_is_reported_per_route` | matches `decide_confidence()` on the best bucket |
| `test_routes.py::test_single_store_read` | monkeypatches `read_frame` and asserts one call |
| `test_routes.py::test_missing_route_file_raises_at_startup` | not a runtime 500 |
| `test_cache.py::test_identical_requests_hit_the_cache` | `predict` called once for two identical posts |
| `test_cache.py::test_different_current_price_misses` | |
| `test_cache.py::test_entry_expires_after_ttl` | injected clock, no sleeping |
| `test_cache.py::test_as_of_date_is_in_the_key` | a date rollover invalidates |
| `test_cache.py::test_disabled_cache_always_misses` | |
| `test_cache.py::test_eviction_at_max_entries` | |
| `test_cache.py::test_clear_is_effective` | the fixture other tests rely on actually works |
| `tests/api/test_predict.py::test_warm_response_under_300ms` | marked `slow`; SF-07's stated target, measured warm on the fixture dataset over 20 calls, asserting the median |
| `tests/api/test_contract.py::test_api_and_baseline_min_cell_observations_agree` | `config/api.yaml serving.min_cell_observations == config/baseline.yaml history.min_cell_observations` |

## 10. Out of scope

Everything SF-07 lists (multi-route search, auth, rate limiting, the trained model), plus:
no `web/` scratch page (SF-08 deferred, decision 0001), no Dockerfile or deployment manifest,
no persistence — the API is read-only and writes nothing but its own log.

## 11. Interfaces frozen for downstream

SF-08 is deferred, so the only downstream consumer today is the committed OpenAPI document.
What it may rely on:

1. Three paths: `GET /health`, `POST /predict`, `GET /routes`. Base path is the root; no
   `/v1` prefix in this phase.
2. `PredictResponse` has exactly the 10 top-level keys of SF-07's documented payload, in
   that order. Adding a key is a spec change.
3. `basis` is serialised with `from` / `to`, not `from_`.
4. Every 4xx/5xx body is `ErrorBody` (`error`, `message`, `field`) — never FastAPI's
   default `{"detail": ...}`.
5. `price_percentile` is `0..100` and **low means cheap** (SF-06-build §8.4).
6. `expected_low` is `null` unless `verdict == "wait"`.
7. `expected_curve` is descending by `days_to_departure`, first point is today's.
8. Thin data / unknown route is a `200`, never a `404` or `500`.
9. `api/openapi.json` is regenerated by `uv run python scripts/dump_openapi.py` and is
   verified current by a test.

## 12. Ordered commit plan

| # | Message | Contains |
|---|---|---|
| 1 | `Add API settings and the shared route loader` | `config/api.yaml`, `api/settings.py`, `shared/routes.py`, `tests/api/conftest.py` |
| 2 | `Define the request and response models` | `api/models.py`, `api/errors.py`, `tests/api/test_predict_validation.py` |
| 3 | `Stand up the app factory and /health` | `api/app.py`, `api/dependencies.py`, `api/routers/health.py`, `tests/api/test_health.py` |
| 4 | `Serve predictions over POST /predict` | `api/routers/predict.py`, `tests/api/test_predict.py` |
| 5 | `Cache identical predict requests for six hours` | `api/cache.py`, `tests/api/test_cache.py` |
| 6 | `List the route set and its history depth` | `api/routers/routes.py`, `tests/api/test_routes.py` |
| 7 | `Commit the OpenAPI document` | `scripts/dump_openapi.py`, `api/openapi.json`, `tests/api/test_openapi.py` |
| 8 | `Pin the response contract` | `tests/api/test_contract.py` |

Push after each. Commit 8 is deliberately last and test-only: the contract is pinned against
the finished API, so a later change that breaks the wire shape fails loudly.
