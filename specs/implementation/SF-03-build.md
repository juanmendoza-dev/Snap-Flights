# SF-03 — Build Spec: Canonical Schema + Snapshot Store + Fixtures

**Tier:** L3 (build spec) · **Parent:** `specs/subfeatures/SF-03-canonical-schema-snapshot-store.md`
**Execution slot:** second, after P0. Blocks SF-06 and SF-07.

## Summary

Implements SF-03 exactly. This file adds no scope; it pins the concrete signatures, the
fixture price model, and the tests that L0 §3/§6/§7 and SF-03 leave abstract.

## Depends on

- P0 scaffold on `main`.
- L0 §1 (routes.csv columns), §2 (naming, ID rule), §3 (schema), §6 (natural key, store), §7 (fixtures).

## Files owned

```
pipeline/schema/__init__.py            # re-exports: FareObservation, enums, validate, observation_id
pipeline/schema/enums.py               # Source, TripType, Cabin, PriceKind, DataQuality, QualityFlag
pipeline/schema/record.py              # the FareObservation Pydantic v2 model + SCHEMA_VERSION
pipeline/schema/arrow.py               # the pinned pyarrow schema + record<->Arrow conversion
pipeline/schema/identity.py            # natural-key canonicalisation + observation_id()
pipeline/schema/validation.py          # validate(), validate_batch(), Violation, BatchReport
pipeline/store/__init__.py             # re-exports: SnapshotStore, ReadFilters, default_store
pipeline/store/filters.py              # the ReadFilters model
pipeline/store/snapshot_store.py       # SnapshotStore: write / read / read_frame
pipeline/store/paths.py                # partition path construction + discovery
shared/__init__.py                     # (exists from P0)
shared/settings.py                     # THE single reader of SNAP_USE_FIXTURES and data roots
scripts/gen_fixtures.py                # deterministic fixture generator (routes.csv + parquet)
scripts/validate_fixtures.py           # body filled in here (skeleton from P0)
data/fixtures/routes.csv               # 15 routes, columns pinned in L0 §1
data/fixtures/fare_observations.parquet  # the committed synthetic history
data/fixtures/README.md                # seed, price model, regen command, expected SHA-256
tests/schema/__init__.py
tests/schema/test_identity.py          # observation_id fixed vectors + stability
tests/schema/test_record.py            # model construction, coercion, nullability
tests/schema/test_validation.py        # every documented bad case
tests/schema/test_arrow.py             # Arrow schema round-trip, dtype pinning
tests/store/__init__.py
tests/store/test_write.py              # partitioning, batch dedup, idempotent re-write
tests/store/test_read.py               # every filter, cross-file dedup, rejected exclusion
tests/store/test_fixture_mode.py       # SNAP_USE_FIXTURES with no data/snapshots/
tests/fixtures/__init__.py
tests/fixtures/test_fixture_dataset.py # shape, determinism, size, schema validity
```

**Not owned:** `.github/workflows/ci.yml` (P0 wired the validation step already — do not edit
it), `config/**` (SF-03 needs no config file).

## 1. Exact file tree

Every path above, one line each, is the tree. Nothing else is created. `data/snapshots/`
stays absent from git; the store creates it at runtime.

## 2. Public signatures

### 2.1 `pipeline/schema/enums.py`

```python
from enum import StrEnum

class Source(StrEnum):
    TRAVELPAYOUTS = "travelpayouts"
    FASTFLIGHTS = "fastflights"

class TripType(StrEnum):
    ONE_WAY = "one_way"
    ROUND_TRIP = "round_trip"

class Cabin(StrEnum):
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"

class PriceKind(StrEnum):
    ITINERARY = "itinerary"
    CALENDAR_CHEAPEST = "calendar_cheapest"

class DataQuality(StrEnum):
    OK = "ok"
    SUSPECT = "suspect"
    REJECTED = "rejected"

class QualityFlag(StrEnum):
    """Flag vocabulary is owned by SF-05 (skipped this pass); the enum is declared here
    because `quality_flags` is a schema field. SF-05 may add members, never rename."""
    SCHEMA_INVALID = "schema_invalid"
    NONPOSITIVE_PRICE = "nonpositive_price"
    PRICE_ABOVE_CEILING = "price_above_ceiling"
    PRICE_BELOW_FLOOR = "price_below_floor"
    PRICE_ZSCORE_EXTREME = "price_zscore_extreme"
    STALE_SOURCE_PRICE = "stale_source_price"
    IMPOSSIBLE_DATES = "impossible_dates"
    UNKNOWN_AIRPORT = "unknown_airport"
```

`Source` is a closed enum today. When SF-01/SF-02 land they add members; the store's
partition path uses the string value, so adding a member is additive.

### 2.2 `pipeline/schema/record.py` — the model in full

```python
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pipeline.schema.enums import Cabin, DataQuality, PriceKind, QualityFlag, Source, TripType

SCHEMA_VERSION: int = 1

INT64_MAX: int = 2**63 - 1

Count = Annotated[int, Field(strict=True, ge=0, le=INT64_MAX)]
PositiveCount = Annotated[int, Field(strict=True, ge=1, le=INT64_MAX)]
AmountMinor = Annotated[int, Field(strict=True, gt=0, le=INT64_MAX)]
SchemaVersion = Annotated[int, Field(strict=True, ge=1, le=INT64_MAX)]

IataCode = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")]
RouteKey = Annotated[str, Field(min_length=7, max_length=7, pattern=r"^[A-Z]{3}-[A-Z]{3}$")]
CurrencyCode = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")]
ObservationId = Annotated[str, Field(min_length=16, max_length=16, pattern=r"^[0-9a-f]{16}$")]


class FareObservation(BaseModel):
    """One price, one trip shape, one source, one moment (L0 §3)."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    observation_id: ObservationId
    source: Source
    source_native_id: str | None = None
    fetched_at: datetime
    observed_price_age_seconds: Count | None = None
    origin: IataCode
    destination: IataCode
    route_key: RouteKey
    depart_date: date
    return_date: date | None = None
    trip_type: TripType
    cabin: Cabin
    passengers: PositiveCount
    stops_outbound: Count | None = None
    stops_return: Count | None = None
    carrier_primary: str | None = Field(default=None, pattern=r"^[A-Z0-9]{2}$")
    amount_minor: AmountMinor
    currency: CurrencyCode
    price_kind: PriceKind
    data_quality: DataQuality = DataQuality.OK
    quality_flags: tuple[QualityFlag, ...] | None = None
    ingest_run_id: str
    schema_version: SchemaVersion = SCHEMA_VERSION

    @field_validator("fetched_at")
    @classmethod
    def _fetched_at_is_utc_aware(cls, v: datetime) -> datetime:
        """tz-aware and UTC (L0 §0). A naive datetime is an error, not something to guess at."""

    @field_validator("ingest_run_id")
    @classmethod
    def _ingest_run_id_is_a_uuid(cls, v: str) -> str:
        """L0 §3 types it as a uuid and L0 §6 puts it straight into a file name. Parsed,
        and kept in the canonical lowercase-hyphenated form."""

    @model_validator(mode="after")
    def _route_key_matches_endpoints(self) -> FareObservation: ...

    @model_validator(mode="after")
    def _return_date_iff_round_trip(self) -> FareObservation:
        """return_date is null iff trip_type == one_way (SF-03 'What to build' §1)."""

    @property
    def fetched_date(self) -> date:
        """UTC calendar date of fetched_at — the partition key and a natural-key field (L0 §6)."""
```

**Bounded, strict integers (review C2).** Every int64-backed field is bounded by the
physical Arrow type rather than by Python's unbounded `int`: `2**63` used to validate here
and raise `OverflowError` during Arrow conversion, after earlier partition groups had
already been published. `strict=True` additionally rejects `True` and `1.0` for a count or
an amount — a boolean price of 1 is not a price. `schema_version` is bounded but not pinned
to `SCHEMA_VERSION` at the field level, so a future v2 file still parses; `validate()` is
what requires the version this code speaks.

**`ingest_run_id` is a UUID (review C2).** It is not a natural-key field, so canonicalising
it cannot move an `observation_id`. It *is* the dedup tiebreaker and a path segment, so one
spelling per run is what makes both well-defined — and an unrestricted string in a file name
is how `x/../../../../../escaped` wrote outside the store root.

Model construction does **not** compute `observation_id`. Producers call
`observation_id(...)` and pass it in; `validate()` checks it matches. This keeps the model a
dumb container and makes a wrong id detectable instead of silently self-healing.

**Flags are a tuple (review C1).** A frozen model whose `quality_flags` is a `list` is not
frozen: the list is mutable in place. Producers may still pass a list; the model stores a
tuple.

Convenience constructor, for adapters and the fixture generator:

```python
def build_observation(
    *,
    source: Source,
    fetched_at: datetime,
    origin: str,
    destination: str,
    depart_date: date,
    trip_type: TripType,
    cabin: Cabin,
    passengers: int,
    amount_minor: int,
    currency: str,
    price_kind: PriceKind,
    ingest_run_id: str,
    return_date: date | None = None,
    stops_outbound: int | None = None,
    stops_return: int | None = None,
    carrier_primary: str | None = None,
    source_native_id: str | None = None,
    observed_price_age_seconds: int | None = None,
    data_quality: DataQuality = DataQuality.OK,
    quality_flags: Sequence[QualityFlag] | None = None,
) -> FareObservation:
    """Derive route_key and observation_id, then construct. The only sanctioned way to
    create a FareObservation from source data."""
```

And the sanctioned way to stamp quality on a frozen record:

```python
def with_quality(
    record: FareObservation,
    *,
    data_quality: DataQuality,
    quality_flags: Sequence[QualityFlag] | None = None,
) -> FareObservation:
    """A revalidated copy carrying a new quality verdict (review C1)."""
```

SF-05 will stamp quality on records that are already built and frozen. `model_copy(update=)`
skips every validator — a copy with `amount_minor=-1` validated clean and reached Parquet —
so the copy is dumped and put back through the model. Field rules only: a record whose
*fields* no longer validate cannot be stamped at all. Representing an invalid record so it
can be quarantined is review S3's open question, owned by SF-05.

### 2.3 `pipeline/schema/identity.py` — canonicalisation, pinned

L0 §6 gives the rule (`sha256(natural key fields joined with "|")[:16]`) but not the
encoding. Pinned here:

| Rule | Value |
|------|-------|
| Field order | exactly L0 §6's list: `source, origin, destination, depart_date, return_date, cabin, passengers, trip_type, stops_outbound, stops_return, carrier_primary, price_kind, fetched_date` |
| `None` | the empty string (`""`) |
| `date` | ISO `YYYY-MM-DD` |
| `int` | base-10 decimal, no padding, no sign for positives |
| `str` / enum | the value verbatim, already normalised (IATA upper, cabin lower) |
| Separator | `\|` (U+007C), between every field, no trailing separator |
| Hash | SHA-256 over UTF-8 bytes of the joined string, lowercase hex, **first 16 characters** |
| `fetched_date` | UTC calendar date of `fetched_at`, **not** the timestamp |

```python
NATURAL_KEY_FIELDS: tuple[str, ...] = (
    "source", "origin", "destination", "depart_date", "return_date", "cabin",
    "passengers", "trip_type", "stops_outbound", "stops_return",
    "carrier_primary", "price_kind", "fetched_date",
)

def natural_key(
    *,
    source: Source | str,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date | None,
    cabin: Cabin | str,
    passengers: int,
    trip_type: TripType | str,
    stops_outbound: int | None,
    stops_return: int | None,
    carrier_primary: str | None,
    price_kind: PriceKind | str,
    fetched_date: date,
) -> str:
    """The canonical join string. Exposed for debugging and for the fixed-vector tests."""

def observation_id(**natural_key_fields: object) -> str:
    """sha256(natural_key(...))[:16]. Same kwargs as natural_key()."""

def observation_id_for(record: FareObservation) -> str:
    """Recompute the id from a record's own fields — used by validate()."""
```

**Fixed vectors** (computed from the rules above; these are the assertions in
`tests/schema/test_identity.py`):

| # | Canonical string | `observation_id` |
|---|------------------|------------------|
| 1 | `travelpayouts\|JFK\|LHR\|2026-12-20\|\|economy\|1\|one_way\|\|\|\|calendar_cheapest\|2026-09-09` | `5477078824fd0f61` |
| 2 | `fastflights\|JFK\|LHR\|2026-12-20\|\|economy\|1\|one_way\|0\|\|BA\|itinerary\|2026-09-09` | `c518122f90afdbd8` |
| 3 | `travelpayouts\|MAD\|LIS\|2027-01-07\|\|economy\|1\|one_way\|\|\|\|calendar_cheapest\|2026-06-12` | `09af5365f2a6bff9` |
| 4 | `fastflights\|LAX\|NRT\|2026-10-01\|\|economy\|1\|one_way\|1\|\|NH\|itinerary\|2026-08-15` | `911acecfc2b32add` |
| 5 | `travelpayouts\|LHR\|JFK\|2026-11-03\|2026-11-10\|business\|2\|round_trip\|0\|1\|VS\|itinerary\|2026-09-09` | `95952155f6787ec0` |

Vector 5 is round-trip/business/2-pax on purpose: out of MVP scope, in schema scope, and it
pins that no natural-key field is dropped when the non-null branches are taken.

Vectors 1 and 2 differ only in source/stops/carrier/price_kind and must produce different
ids — the test asserts that explicitly, not just the literals.

### 2.4 `pipeline/schema/validation.py`

```python
from dataclasses import dataclass
from enum import StrEnum

class ViolationCode(StrEnum):
    MISSING_REQUIRED = "missing_required"
    WRONG_TYPE = "wrong_type"
    BAD_ENUM = "bad_enum"
    BAD_IATA = "bad_iata"
    BAD_CURRENCY = "bad_currency"
    BAD_ROUTE_KEY = "bad_route_key"
    NAIVE_TIMESTAMP = "naive_timestamp"
    NON_UTC_TIMESTAMP = "non_utc_timestamp"
    NONPOSITIVE_AMOUNT = "nonpositive_amount"
    RETURN_DATE_MISMATCH = "return_date_mismatch"
    OBSERVATION_ID_MISMATCH = "observation_id_mismatch"
    BAD_SCHEMA_VERSION = "bad_schema_version"
    OUT_OF_RANGE = "out_of_range"          # an int64 field outside its bounds (review C2)
    BAD_INGEST_RUN_ID = "bad_ingest_run_id"  # not a UUID (review C2)

@dataclass(frozen=True, slots=True)
class Violation:
    code: ViolationCode
    field: str | None
    detail: str

@dataclass(frozen=True, slots=True)
class BatchReport:
    total: int
    valid: int
    invalid: int
    counts_by_code: dict[ViolationCode, int]
    sample: list[tuple[int, Violation]]   # (row index, violation), capped at 20

    @property
    def ok(self) -> bool: ...

def validate(record: FareObservation | dict[str, object]) -> list[Violation]:
    """Empty list == valid. Accepts a raw dict (from Parquet) or a built model."""

def validate_batch(records: Iterable[FareObservation | dict[str, object]]) -> BatchReport:
    """Structured report with counts by violation type (SF-03 'What to build' §1)."""

class InvalidBatchError(ValueError):
    """A batch crossing a trust boundary contained invalid rows; carries the BatchReport."""
    report: BatchReport

def validated_batch(records: Iterable[FareObservation | dict[str, object]]) -> list[FareObservation]:
    """Every row revalidated and rebuilt, or InvalidBatchError with the full report."""

def logical_violations(record: FareObservation) -> list[Violation]:
    """The id-recomputes and schema-version rules alone, for a record already built."""
```

**A model instance is not evidence (review C1).** `validate()` used to check only the id and
the schema version when handed a `FareObservation`, on the theory that construction had
already enforced the rest. `model_copy(update=...)` and `model_construct()` both produce
instances that never met a validator, so a copy with `amount_minor=-1` reported no
violations, was written, came back as `-1` from `read_frame()` and raised from `read()`.
Every entry point now revalidates from the record's own dumped field values, and
`validated_batch()` is the shared trust boundary the store writes and canonical
reconstruction both go through.

The documented bad cases `validate()` must reject, one test each (§8):
naive `fetched_at`; non-UTC `fetched_at`; lowercase or 2-letter IATA; lowercase currency;
`route_key` disagreeing with `origin`/`destination`; `amount_minor` of `0` and of `-1`;
`return_date` set on a `one_way`; `return_date` null on a `round_trip`; an enum value
outside `Cabin`/`PriceKind`/`Source`/`DataQuality`; an `observation_id` that does not
recompute; `schema_version` != 1; a boolean or integral-float in an int64 field; an int64
field above `INT64_MAX` or a negative `observed_price_age_seconds`; an `ingest_run_id` that
is not a UUID.

`NONPOSITIVE_AMOUNT` is `amount_minor`'s **lower**-bound code only. An `amount_minor` above
`INT64_MAX` reports `OUT_OF_RANGE`, like every other int64 bound failure — calling `2**63`
"nonpositive" would be worse than useless to a quarantine report.

### 2.5 `pipeline/schema/arrow.py` — the pinned physical schema

Every nullable column in the fixture is written with an explicit type so Arrow cannot infer
`null` for an all-null column (`return_date`, `stops_return`, `quality_flags` are all-null in
this pass) and so the timestamp unit never drifts across DuckDB / polars / pyarrow.

```python
import pyarrow as pa

FARE_OBSERVATION_ARROW_SCHEMA: pa.Schema = pa.schema([
    pa.field("observation_id",             pa.string(),                       nullable=False),
    pa.field("source",                     pa.string(),                       nullable=False),
    pa.field("source_native_id",           pa.string(),                       nullable=True),
    pa.field("fetched_at",                 pa.timestamp("us", tz="UTC"),      nullable=False),
    pa.field("observed_price_age_seconds", pa.int64(),                        nullable=True),
    pa.field("origin",                     pa.string(),                       nullable=False),
    pa.field("destination",                pa.string(),                       nullable=False),
    pa.field("route_key",                  pa.string(),                       nullable=False),
    pa.field("depart_date",                pa.date32(),                       nullable=False),
    pa.field("return_date",                pa.date32(),                       nullable=True),
    pa.field("trip_type",                  pa.string(),                       nullable=False),
    pa.field("cabin",                      pa.string(),                       nullable=False),
    pa.field("passengers",                 pa.int64(),                        nullable=False),
    pa.field("stops_outbound",             pa.int64(),                        nullable=True),
    pa.field("stops_return",               pa.int64(),                        nullable=True),
    pa.field("carrier_primary",            pa.string(),                       nullable=True),
    pa.field("amount_minor",               pa.int64(),                        nullable=False),
    pa.field("currency",                   pa.string(),                       nullable=False),
    pa.field("price_kind",                 pa.string(),                       nullable=False),
    pa.field("data_quality",               pa.string(),                       nullable=False),
    pa.field("quality_flags",              pa.list_(pa.string()),             nullable=True),
    pa.field("ingest_run_id",              pa.string(),                       nullable=False),
    pa.field("schema_version",             pa.int64(),                        nullable=False),
])

COLUMN_ORDER: tuple[str, ...] = tuple(FARE_OBSERVATION_ARROW_SCHEMA.names)

def records_to_table(records: Sequence[FareObservation]) -> pa.Table:
    """Column order is COLUMN_ORDER, types are FARE_OBSERVATION_ARROW_SCHEMA. Enums are
    written as their string values, never as Arrow dictionaries."""

def table_to_records(table: pa.Table) -> list[FareObservation]:
    """Inverse. Raises on a schema mismatch rather than coercing."""
```

`source` and `route_key` are Hive-encoded in the path **and** kept as columns in the file.
Redundant on disk, but it makes a single part file self-describing and lets `read()` fall
back to a plain file scan.

`fetched_date` is a **path segment only**. It is not in the schema above, because L0 §3 has
no such field: it is the UTC calendar date of `fetched_at` and is derived, never stored. A
query filtering on it computes `CAST(fetched_at AS DATE)` with the connection's `TimeZone`
set to `UTC` — that cast is session-timezone dependent, and `fetched_date` is defined in UTC
(L0 §6).

Because the two partition columns are also real columns, every scan runs with
**`hive_partitioning = 0`**. With Hive inference on, DuckDB and pyarrow re-derive `source`
and `route_key` from the path as dictionary-typed columns and collide with the file's own
string columns (`Unable to merge: Field source has incompatible types: string vs
dictionary`). Keeping the columns in the file is the decision that makes inference redundant,
so it is turned off rather than worked around.

`table_to_records()` revalidates every row, id and schema version included (review C1):
matching the physical schema says the bytes are shaped right, not that the id recomputes
from the natural key it claims. It raises `InvalidBatchError`.

### 2.6 `shared/settings.py` — the single fixture-mode reader

Read `SNAP_USE_FIXTURES` in exactly one place so `pipeline/`, `models/` and `api/` cannot
disagree about which mode they are in.

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True, slots=True)
class DataSettings:
    repo_root: Path
    snapshots_root: Path       # {repo_root}/data/snapshots/fare_observations
    fixtures_root: Path        # {repo_root}/data/fixtures
    use_fixtures: bool         # SNAP_USE_FIXTURES in {"1","true","yes"} (case-insensitive)

    @property
    def fixture_parquet(self) -> Path: ...   # fixtures_root/fare_observations.parquet

    @property
    def routes_csv(self) -> Path: ...        # fixtures_root/routes.csv

def load_data_settings(
    *, repo_root: Path | None = None, use_fixtures: bool | None = None
) -> DataSettings:
    """Explicit arguments win over the environment; the environment wins over defaults.
    repo_root defaults to the package root two levels above this file."""

def use_fixtures() -> bool:
    """Convenience accessor. api/'s /health fixture flag reads THIS, nothing else."""
```

### 2.7 `pipeline/store/filters.py`

```python
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RouteKeyFilter = Annotated[str, Field(pattern=r"^[A-Z]{3}-[A-Z]{3}$")]
Limit = Annotated[int, Field(strict=True, ge=0)]


class ReadFilters(BaseModel):
    """Every filter is AND-ed. None means 'no constraint on this dimension'.
    Date/timestamp ranges are inclusive on both ends. An empty list means 'nothing
    matches' and returns an empty result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Source | Sequence[Source] | None = None
    route_key: RouteKeyFilter | Sequence[RouteKeyFilter] | None = None
    fetched_date_from: date | None = None
    fetched_date_to: date | None = None
    fetched_at_from: datetime | None = None     # tz-aware UTC; narrows within a fetched_date
    fetched_at_to: datetime | None = None
    depart_date_from: date | None = None
    depart_date_to: date | None = None
    price_kind: PriceKind | Sequence[PriceKind] | None = None
    data_quality: DataQuality | Sequence[DataQuality] | None = None
    include_rejected: bool = False              # L0 §6: rejected excluded unless asked
    limit: Limit | None = None

    @field_validator("fetched_at_from", "fetched_at_to")
    @classmethod
    def _cutoff_is_utc_aware(cls, v: datetime | None) -> datetime | None:
        """tz-aware UTC, the same contract as the record's own fetched_at (L0 §0)."""

    @model_validator(mode="after")
    def _ranges_are_ordered(self) -> ReadFilters: ...

    @property
    def selects_nothing(self) -> bool:
        """True when some dimension was given an explicitly empty list."""
```

**What the filters check, pinned (review C3).** Everything a caller can express is validated
at construction rather than by DuckDB halfway through a query:

| Input | Behaviour |
|---|---|
| `route_key=[]` (or any empty list) | an empty result with the frozen §6 schema, short-circuited before SQL — `IN ()` is a parser error, and the answer must not depend on whether the store holds data yet |
| `limit=-1`, `limit=True`, `limit="10"` | `ValidationError`; `limit=0` is a legitimate empty result |
| naive or non-UTC `fetched_at_*` | `ValidationError`. The query runs under a UTC session, so a naive local cutoff was silently reinterpreted |
| `*_from` after `*_to` | `ValidationError` (`reversed_range`); `from == to` is a valid one-instant window |
| a route key that is not `ORG-DST` | `ValidationError`. A well-formed route with no rows is simply empty |

Precedence rule, pinned: when `data_quality` is set explicitly it wins outright and
`include_rejected` is ignored. When `data_quality` is `None`, rows with
`data_quality == "rejected"` are excluded unless `include_rejected=True`.

### 2.8 `pipeline/store/snapshot_store.py`

```python
class SnapshotStore:
    def __init__(self, settings: DataSettings | None = None) -> None:
        """settings defaults to load_data_settings()."""

    def write(self, records: Sequence[FareObservation]) -> WriteResult:
        """Validate the whole batch, then group by (source, route_key, fetched_date);
        dedup within the batch on observation_id keeping the LAST occurrence; write one
        part-{ingest_run_id}.parquet per group under the L0 §6 layout. Never rewrites
        or deletes an existing file: if the target path exists, a numeric suffix is
        appended (part-{run}-002.parquet). Empty batch is a no-op returning zeros.
        Raises InvalidBatchError (carrying the BatchReport) if any record is invalid."""

    def read(self, filters: ReadFilters | None = None) -> list[FareObservation]:
        """Spec-literal path: canonical records. Convenience for tests and small reads.
        Do not call this for whole-route history — use read_frame()."""

    def read_frame(self, filters: ReadFilters | None = None) -> pl.DataFrame:
        """Bulk path. Same rows, same filtering, same dedup as read(), returned as a
        polars DataFrame with the frozen schema in §7. This is what models/ uses."""

    def sources_with_recent_data(self, *, within_days: int = 3, as_of: date | None = None
                                 ) -> dict[str, date]:
        """source -> most recent fetched_date, for sources seen within the window
        [as_of - within_days, as_of], INCLUSIVE at both ends; within_days is a
        nonnegative plain int and 0 means "as_of only".
        `as_of` defaults to shared.clock.today_utc() — never date.today(), so a pinned
        SNAP_TODAY makes /health deterministic against the fixture calendar (P0 §Interfaces
        frozen 8). Backs GET /health (SF-07)."""


@dataclass(frozen=True, slots=True)
class WriteResult:
    files_written: int
    records_written: int
    duplicates_dropped: int
    paths: list[Path]


def default_store() -> SnapshotStore:
    """Process-wide store built from load_data_settings(). Cached."""
```

**Validation is mandatory and comes first (review C1/C2).** `write()` is the store's trust
boundary: every record is rebuilt from its own field values before anything is grouped,
deduped or published, and an invalid batch raises `InvalidBatchError` before a single file
lands. Arrow conversion of every group also happens before the first write — an int64
overflow used to fail mid-publication with earlier partitions already on disk, and an
append-only store cannot take those back.

`read()` revalidates again on canonical reconstruction. `read_frame()` does **not**, and is
not meant to: it is the bulk path, and revalidating a whole training scan row by row would
defeat its purpose. The two agree on every row that came in through `write()`; a row planted
under the store root by something other than the store is refused by `read()` and returned by
`read_frame()`.

`read()` and `read_frame()` share one DuckDB query built by a private
`_build_query(filters) -> tuple[str, list[object]]`, so the two can never diverge. `read()`
is `table_to_records(read_frame(...).to_arrow())`.

**Dedup, pinned.** DuckDB window function over the union of matched files:

```sql
SELECT * EXCLUDE (rn) FROM (
  SELECT *, row_number() OVER (
    PARTITION BY observation_id
    ORDER BY fetched_at DESC, ingest_run_id DESC
  ) AS rn
  FROM scanned
) WHERE rn = 1
```

`ingest_run_id DESC` is the tiebreaker when two files carry the same `observation_id` with
an identical `fetched_at` — without it "last wins" is not deterministic. L0 §6 says later
`fetched_at` wins and is silent on the tie; this makes the result reproducible.

**Fixture union, pinned.** When `settings.use_fixtures` is true, the scanned relation is
`data/fixtures/fare_observations.parquet` UNION ALL the snapshot part files (if any). The
same `observation_id` in both resolves by the dedup rule above, so a real observation
naturally supersedes a fixture row with the same natural key. With no `data/snapshots/`
directory present, the union degrades to the fixture file alone and does not error.
When `use_fixtures` is false and no snapshots exist, `read()` returns `[]` and
`read_frame()` returns an **empty frame with the full schema**, never a zero-column frame.

### 2.9 `pipeline/store/paths.py`

```python
def partition_dir(root: Path, *, source: str, route_key: str, fetched_date: date) -> Path:
    """{root}/source={source}/route_key={route_key}/fetched_date={YYYY-MM-DD}"""

def part_path(root: Path, *, source: str, route_key: str, fetched_date: date,
              ingest_run_id: str, attempt: int = 1) -> Path:
    """.../part-{ingest_run_id}.parquet for attempt 1, part-{ingest_run_id}-{attempt:03d}
    .parquet after."""

def scan_glob(root: Path) -> str:
    """{root}/source=*/route_key=*/fetched_date=*/part-*.parquet — the DuckDB read_parquet
    argument, with hive_partitioning=0 (the partition columns are in the file; see §2.5)."""

def under_root(root: Path, target: Path) -> Path:
    """`target`, asserted to resolve inside `root` (both sides resolved first, since the
    store root may be a symlink). ValueError otherwise."""
```

**Path components are checked here too (review C2).** Every partition value must be a single
safe segment — `^[A-Za-z0-9][A-Za-z0-9._-]*$`, never `.` or `..` — and every constructed path
is asserted to stay under the store root. The model already bounds what can reach these
functions, but the store owns its own filesystem boundary: a run id of
`x/../../../../../escaped` wrote `data/snapshots/escaped.parquet`, outside the scan tree.

## 3. Config file schemas

**None.** SF-03 introduces no config file. `config/routes.yaml` is SF-04's and is not created
this pass; `data/fixtures/routes.csv` is the only route list that exists (see
`specs/implementation/README.md` open question 3).

## 4. Fixture generator design

`scripts/gen_fixtures.py`. Deterministic by construction: **no RNG object anywhere.** Every
pseudo-random quantity is a pure function of a SHA-256 of the seed plus the cell key, so the
output does not depend on iteration order, parallelism, or Python's hash seed.

```python
SEED: str = "snap-flights-fixtures-v1"
FIXTURE_TODAY: date = date(2026, 9, 9)          # the "as of" date the dataset is built around
                                                # MUST equal CI's SNAP_TODAY (P0 ci.yml env)
FETCHED_DAYS: int = 90                          # fetched_date in [2026-06-12 .. 2026-09-09]
DTD_GRID: range = range(1, 121)                 # days-to-departure 1..120, per fetched_date
ITINERARY_MAX_DTD: int = 60                     # itinerary rows only inside this window
FIXTURE_CURRENCY: str = "USD"                   # single currency; see note below

def _h(*parts: object) -> int:
    """int(sha256(SEED + "|" + "|".join(str(p) for p in parts)).hexdigest(), 16)"""

def _unit(*parts: object) -> float:
    """_h(*parts) % 10**9 / 10**9  -> a stable float in [0, 1)"""
```

**`FIXTURE_TODAY` and CI's `SNAP_TODAY` are one value in two files.** The generator
anchors the dataset's newest `fetched_date` here; `.github/workflows/ci.yml` pins
`SNAP_TODAY: "2026-09-09"` so `shared.clock.today_utc()` returns that same day. If they ever
disagree, "today" lands outside the fixture calendar and every recency, `days_to_departure`
and `depart_date`-validation assertion in SF-06/SF-07 goes quietly wrong. The generator does
not read the environment — it stays a hardcoded constant so regeneration is reproducible —
so the two are kept honest by a test instead:
`tests/fixtures/test_fixture_dataset.py::test_fixture_today_matches_ci_snap_today` parses
`.github/workflows/ci.yml` and asserts `env.SNAP_TODAY == FIXTURE_TODAY.isoformat()`.
Reading that file from a test is not editing it; SF-03 still owns none of it.

### 4.1 Grid

`depart_date = fetched_date + dtd`, for every `dtd` in `DTD_GRID`.

This is the reading of L0 §7's "15 routes × ~120 departure dates × daily `fetched_at` for
~90 days": 15 × 120 × 90 = 162,000, which is exactly the arithmetic in L0 §7, and it is the
only reading where every advance-purchase bucket has coverage at every `fetched_date`. A
fixed calendar window of 120 departure dates would leave the short buckets empty for the
first two months of history. Distinct departure dates across the whole file: 2026-06-13 →
2027-01-07 (209 dates).

### 4.2 Routes — `data/fixtures/routes.csv`

Columns exactly as pinned in L0 §1, in this order, comma-separated, `\n` line endings, one
header row, rows sorted by `route_key`:

```csv
route_key,origin,destination,region,tier
ATL-MIA,ATL,MIA,domestic-us,3
BOS-DUB,BOS,DUB,transatlantic,2
CDG-FCO,CDG,FCO,intra-europe,3
JFK-CDG,JFK,CDG,transatlantic,2
JFK-LAX,JFK,LAX,domestic-us,1
JFK-LHR,JFK,LHR,transatlantic,1
LAX-JFK,LAX,JFK,domestic-us,1
LAX-NRT,LAX,NRT,transpacific,1
LHR-BCN,LHR,BCN,intra-europe,2
LHR-JFK,LHR,JFK,transatlantic,1
MAD-LIS,MAD,LIS,intra-europe,3
ORD-DEN,ORD,DEN,domestic-us,2
SEA-ICN,SEA,ICN,transpacific,3
SFO-HND,SFO,HND,transpacific,2
SFO-LHR,SFO,LHR,transatlantic,2
```

15 routes: 5 tier-1, 6 tier-2, 4 tier-3, across four regions, with `JFK-LHR`/`LHR-JFK` and
`JFK-LAX`/`LAX-JFK` present in both directions to exercise L0 §2's directional route key.

### 4.3 Price model

```
amount_minor(route, depart_date, fetched_date, price_kind)
  = round_to_100(
        base_minor[route]
      * seasonal[month(depart_date)]
      * dow[weekday(depart_date)]
      * ap_multiplier(route, month(depart_date), dtd)
      * (1 + noise(route, depart_date, fetched_date))
      * itinerary_premium            # 1.0 for calendar_cheapest
    )
```

`round_to_100` rounds to whole currency units (money is integer minor units — L0 §0 — and
airfares are not quoted in cents).

**Base price per route** (USD minor, one-way economy, 1 adult):

| route | base | route | base | route | base |
|---|---|---|---|---|---|
| `JFK-LHR` | 42000 | `SFO-LHR` | 51000 | `JFK-LAX` | 19000 |
| `LHR-JFK` | 39000 | `LAX-NRT` | 62000 | `LAX-JFK` | 18500 |
| `JFK-CDG` | 44000 | `SFO-HND` | 58000 | `ORD-DEN` | 12500 |
| `BOS-DUB` | 38000 | `SEA-ICN` | 55000 | `ATL-MIA` | 11000 |
| `LHR-BCN` | 7500 | `CDG-FCO` | 8200 | `MAD-LIS` | 6400 |

**Seasonal multiplier, by month of travel** (one global table; route-specific seasonality is
not needed for the baseline to work and adds 15× the numbers to review):

| Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.88 | 0.86 | 0.94 | 1.02 | 1.06 | 1.18 | 1.28 | 1.24 | 1.00 | 0.96 | 0.92 | 1.20 |

**Day-of-week multiplier, by weekday of travel** (Mon=0):

| Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|
| 1.00 | 0.94 | 0.95 | 1.02 | 1.12 | 1.06 | 1.10 |

**Advance-purchase curve.** Shape is assigned per `(route_key, YYYY-MM of depart_date)`:

```python
def ap_shape(route_key: str, travel_month: str) -> str:
    return "dip" if _h("shape", route_key, travel_month) % 2 == 0 else "rising"

def rising(dtd: int) -> float:
    return 0.98 + 0.62 * math.exp(-dtd / 38.0)

def ap_multiplier(route_key: str, travel_month: str, dtd: int) -> float:
    m = rising(dtd)
    if ap_shape(route_key, travel_month) == "rising":
        return m
    h = _h("dip", route_key, travel_month)
    t0 = 20 + h % 26                      # trough centre, 20..45 days out
    depth = 0.10 + (h // 26 % 81) / 1000.0  # 0.100..0.180
    return m * (1.0 - depth * math.exp(-((dtd - t0) ** 2) / (2 * 6.0**2)))
```

- `rising` is monotone decreasing in `dtd`: ×1.01 at 120 days out, ×1.11 at 60, ×1.34 at 21,
  ×1.50 at 7, ×1.58 at 1. This is the classic "book early, it climbs" shape SF-03 asks for.
- `dip` is the same curve with a Gaussian trough of 10–18% centred 20–45 days out and
  σ = 6 days — SF-03's "10–18% trough somewhere between 45 and 20 days out before rising
  again", literally.
- The split is a parity test on a hash, so it is ~50/50 over the 15 routes × 8 travel months
  present, and **stable**: the same route/month always gets the same shape. The generator
  writes the realised split into `data/fixtures/README.md` and the test asserts it lands in
  40–60%.

**Noise:** `noise = (_unit("noise", route_key, depart_date, fetched_date) - 0.5) * 0.06` →
±3%, per cell, independent of the price level.

**Itinerary rows.** Emitted only for **tier-1 routes** (`JFK-LHR`, `LHR-JFK`, `LAX-NRT`,
`JFK-LAX`, `LAX-JFK`) and only for `dtd <= 60` — the same restriction SF-04 puts on
fast-flights (tier-1 only, capped volume), so the fixture looks like what the real pipeline
would produce.

- `itinerary_premium = 1.0 + _unit("prem", route_key, depart_date, fetched_date) * 0.08`
  (0–8% above the calendar cheapest — an itinerary is a *specific bookable* option, so it is
  never cheaper than the route-level cheapest).
- `stops_outbound = 0` if `_unit("stops", ...) < 0.55` else `1`.
- `carrier_primary` from a fixed per-route list, chosen by `_h("carrier", ...) % len(list)`:
  `JFK-LHR`/`LHR-JFK` → `["BA","VS","AA","DL"]`; `LAX-NRT` → `["NH","JL","UA"]`;
  `JFK-LAX`/`LAX-JFK` → `["AA","DL","B6","UA"]`.

**Row counts:**

| Stream | Rows |
|---|---|
| `calendar_cheapest`, `source=travelpayouts`, all 15 routes, dtd 1–120 | 15 × 120 × 90 = **162,000** |
| `itinerary`, `source=fastflights`, 5 tier-1 routes, dtd 1–60 | 5 × 60 × 90 = **27,000** |
| **Total** | **189,000** |

**Provenance / nullable columns** — deliberately not all-null, so validators and SF-05 have
something to bite on:

| Field | `calendar_cheapest` | `itinerary` |
|---|---|---|
| `source` | `travelpayouts` | `fastflights` |
| `fetched_at` | `{fetched_date}T06:00:00Z` | `{fetched_date}T06:00:00Z` |
| `source_native_id` | `null` | `ff-{observation_id[:10]}` |
| `observed_price_age_seconds` | 3600–172800 (1h–48h); a stable 2% subset gets 691200–1209600 (8–14 days) so SF-05's `stale_source_price` (>7d) has cases | `null` (scraper reads live) |
| `stops_outbound` | `null` | `0` or `1` |
| `stops_return` | `null` | `null` |
| `carrier_primary` | `null` | per-route list above |
| `return_date` | `null` | `null` |
| `trip_type` | `one_way` | `one_way` |
| `cabin` | `economy` | `economy` |
| `passengers` | `1` | `1` |
| `currency` | `USD` | `USD` |
| `data_quality` | `ok` | `ok` |
| `quality_flags` | `null` (never `[]`) | `null` |
| `ingest_run_id` | `uuid5(NAMESPACE_URL, f"https://snap.flights/fixtures/{fetched_date}")` | same value — one run per fetched_date |
| `schema_version` | `1` | `1` |

Every row is `data_quality = "ok"`, including the injected error fares. That is L0 §3's rule
("never set `data_quality` yourself beyond the default `ok` — that's the gates' job") and it
is what leaves SF-05 something to catch when it is eventually built. Single currency (`USD`)
throughout: L0 forbids conversion, so a mixed-currency fixture would make percentiles
meaningless without an FX layer nobody has specced.

### 4.4 Error-fare injection

12 outliers, per SF-03. Injected **after** the normal rows are generated, as a fixed fraction
of the (route, AP-bucket) median rather than of the cell's expected price:

1. Generate all 189,000 normal rows.
2. Compute `median(amount_minor)` per `(route_key, ap_bucket)` over the
   `calendar_cheapest` rows. Over 90 fetched dates this **is** the trailing-90-day median
   SF-05's floor is defined against.
3. Overwrite `amount_minor` on 12 fixed cells with `round_to_100(0.22 × bucket_median)`.

`0.22 < 0.35` guarantees SF-05's `price_below_floor` fires when it is built, which
"70–85% below the expected price" does not — the expected price for a cell carries the
seasonal, DOW and noise multipliers, so a cell that is already 25% below its bucket median
can sit above the floor at 85% off. The generator prints the realised "% below expected"
per outlier into `data/fixtures/README.md` for the record; on this price model it lands in
the 72–83% band SF-03 describes. See `specs/implementation/README.md` open question 5.

The 12 cells are a committed literal in the generator (not sampled), spread over 8 routes,
all three tiers, and 5 different AP buckets:

```python
ERROR_FARE_CELLS: tuple[tuple[str, date, int], ...] = (   # (route_key, fetched_date, dtd)
    ("JFK-LHR", date(2026, 6, 20), 17),
    ("JFK-LHR", date(2026, 8, 2),  73),
    ("LHR-JFK", date(2026, 7, 11), 41),
    ("LAX-NRT", date(2026, 6, 28), 96),
    ("LAX-NRT", date(2026, 8, 19), 12),
    ("SFO-LHR", date(2026, 7, 3),  55),
    ("BOS-DUB", date(2026, 9, 1),  29),
    ("JFK-LAX", date(2026, 6, 15), 6),
    ("JFK-LAX", date(2026, 8, 25), 84),
    ("ORD-DEN", date(2026, 7, 22), 33),
    ("ATL-MIA", date(2026, 6, 30), 108),
    ("MAD-LIS", date(2026, 8, 8),  47),
)
```

Only the `calendar_cheapest` row of each cell is overwritten; where a tier-1 itinerary row
exists for the same cell it keeps its normal price. That is realistic (one source glitches,
the other does not) and it means SF-06's "prefer `itinerary`" rule hides some outliers — which
is the correct behaviour to have data for.

**Effect on the model, stated so nobody hunts for it:** SF-06 builds `expected_curve` from
**medians, never minima**, so 12 outliers in 189,000 rows cannot move `expected_low`. They
move percentiles by at most 12/189,000.

### 4.5 Writing the Parquet file — byte identity

L0 §7 requires a byte-reproducible file. Write with `pyarrow.parquet.write_table` directly —
not through polars or DuckDB, whose writer defaults are not part of any contract — with every
knob explicit:

```python
pq.write_table(
    table,                                   # schema = FARE_OBSERVATION_ARROW_SCHEMA
    path,
    compression="zstd",
    compression_level=3,
    row_group_size=64_000,
    use_dictionary=["source", "origin", "destination", "route_key", "trip_type",
                    "cabin", "currency", "price_kind", "data_quality", "ingest_run_id"],
    write_statistics=True,
    version="2.6",
    store_schema=True,
    write_page_index=False,
)
```

Row order is pinned and sorted before writing:
`(route_key, price_kind, fetched_date, depart_date)`, all ascending.

`data/fixtures/README.md` records the expected SHA-256 of the file. Byte identity holds for
a fixed pyarrow version — P0 pins pyarrow to one minor for exactly this reason, and the
writer version is embedded in the file's `created_by` metadata. A pyarrow bump means
regenerate, re-check the SHA into the README, and review the diff — which is precisely the
"deliberate, reviewed change" L0 §7 asks for.

### 4.6 Generator CLI

```python
def main(argv: list[str] | None = None) -> int:
    """--out DIR (default data/fixtures) --check (generate to a temp dir and compare
    bytes against the committed file; exit 1 on mismatch, write nothing)."""
```

## 5. `scripts/validate_fixtures.py` — body

Reads `data/fixtures/fare_observations.parquet` with pyarrow, asserts the file schema equals
`FARE_OBSERVATION_ARROW_SCHEMA` field-for-field (name, type, nullability), runs
`validate_batch()` over every row, prints the `BatchReport`, and returns `1` if
`report.invalid > 0` or the schema differs. Also validates `routes.csv` columns against L0 §1.

**A missing input file is a failure (review C6).** P0 exited 0 with a skip notice, because
no fixture had been generated yet; SF-03 generates it, and a check that validated nothing is
not a check that passed — a typo'd path or a fixture missing from a deployment used to be
reported as success. `--allow-missing` restores the skip for a tree without generated
fixtures; CI and operational checks do not pass it.

## 6. Frozen frame schema — `read_frame()`

**This is the interface SF-06 is built against.** Column order is `COLUMN_ORDER` (§2.5);
dtypes:

| Column | polars dtype |
|---|---|
| `observation_id`, `source`, `source_native_id`, `origin`, `destination`, `route_key`, `trip_type`, `cabin`, `carrier_primary`, `currency`, `price_kind`, `data_quality`, `ingest_run_id` | `pl.String` |
| `fetched_at` | `pl.Datetime(time_unit="us", time_zone="UTC")` |
| `depart_date`, `return_date` | `pl.Date` |
| `observed_price_age_seconds`, `passengers`, `stops_outbound`, `stops_return`, `amount_minor`, `schema_version` | `pl.Int64` |
| `quality_flags` | `pl.List(pl.String)` |

Enum-valued columns are plain `pl.String` (their `StrEnum` value), never `pl.Categorical` —
categoricals carry a per-frame string cache that makes joins across two frames unreliable.

## 7. Test list — mapped to SF-03's Done when

| SF-03 "Done when" bullet | Test |
|---|---|
| `validate()` rejects each documented bad case | `tests/schema/test_validation.py::test_rejects_naive_fetched_at`, `::test_rejects_non_utc_fetched_at`, `::test_rejects_lowercase_iata`, `::test_rejects_two_letter_iata`, `::test_rejects_lowercase_currency`, `::test_rejects_route_key_endpoint_mismatch`, `::test_rejects_zero_amount`, `::test_rejects_negative_amount`, `::test_rejects_return_date_on_one_way`, `::test_rejects_missing_return_date_on_round_trip`, `::test_rejects_unknown_cabin`, `::test_rejects_unknown_price_kind`, `::test_rejects_unknown_source`, `::test_rejects_observation_id_mismatch`, `::test_rejects_wrong_schema_version` |
| … and accepts every fixture row | `tests/fixtures/test_fixture_dataset.py::test_every_fixture_row_validates` (asserts `validate_batch(...).invalid == 0` over all 189,000 rows) |
| `observation_id()` passes fixed-vector tests | `tests/schema/test_identity.py::test_fixed_vectors` (the 5 rows in §2.3, canonical string **and** id), `::test_null_fields_encode_as_empty_string`, `::test_field_order_matches_l0_section_6` |
| … and is stable across runs | `tests/schema/test_identity.py::test_stable_across_processes` (recomputes in a `subprocess` with `PYTHONHASHSEED=random` and compares), `::test_distinct_sources_give_distinct_ids` |
| `write()` then re-`write()`: `read()` returns exactly one copy | `tests/store/test_write.py::test_rewrite_same_batch_is_idempotent_on_read`, `::test_second_write_creates_a_second_part_file` (physical duplication is expected), `::test_batch_dedup_keeps_last_occurrence` |
| `read()` with each filter type returns the expected subset | `tests/store/test_read.py::test_filter_source`, `::test_filter_route_key_single`, `::test_filter_route_key_many`, `::test_filter_fetched_date_range`, `::test_filter_fetched_at_range`, `::test_filter_depart_date_range`, `::test_filter_price_kind`, `::test_filter_data_quality`, `::test_rejected_excluded_by_default`, `::test_include_rejected_flag`, `::test_explicit_data_quality_overrides_include_rejected`, `::test_limit`, `::test_cross_file_dedup_keeps_latest_fetched_at`, `::test_dedup_tiebreak_on_ingest_run_id`, `::test_empty_result_keeps_full_schema` |
| `SNAP_USE_FIXTURES=1` makes `read()` return fixture rows with no `data/snapshots/` | `tests/store/test_fixture_mode.py::test_reads_fixtures_with_no_snapshots_dir`, `::test_fixture_mode_off_returns_empty`, `::test_snapshot_row_supersedes_fixture_row_on_same_id`, `::test_use_fixtures_env_parsing` |
| CI validates every fixture row and fails on any violation | `tests/fixtures/test_fixture_dataset.py::test_validate_fixtures_script_exits_zero`, `::test_validate_fixtures_script_exits_one_on_a_corrupted_copy` (P0 already wired the CI step) |
| `scripts/gen_fixtures.py` run twice produces identical output | `tests/fixtures/test_fixture_dataset.py::test_regeneration_is_byte_identical` (marked `slow`; regenerates to `tmp_path` and compares SHA-256 to the committed file), `::test_sha256_matches_readme` |

Additional tests not tied to a Done-when bullet but required by this build spec:

| Test | Asserts |
|---|---|
| `tests/schema/test_arrow.py::test_arrow_schema_is_pinned` | the literal field list, types and nullability of §2.5 |
| `tests/schema/test_arrow.py::test_records_table_roundtrip` | `table_to_records(records_to_table(r)) == r`, timestamp unit preserved as `us`/UTC |
| `tests/schema/test_record.py::test_frozen_and_extra_forbidden` | model rejects unknown fields and mutation |
| `tests/schema/test_record.py::test_fetched_date_property` | UTC date of `fetched_at`, including a `23:30Z` case |
| `tests/store/test_read.py::test_read_frame_schema_is_frozen` | the §6 column order and dtype table exactly |
| `tests/store/test_read.py::test_read_matches_read_frame` | both paths return the same observation ids for the same filters |
| `tests/store/test_write.py::test_write_rejects_a_negative_price_carried_in_by_model_copy` | review C1's reproduction: `InvalidBatchError`, nothing written |
| `tests/store/test_write.py::test_write_rejects_a_record_whose_id_does_not_recompute` | wrong-id write refused |
| `tests/store/test_write.py::test_write_rejects_an_overflowing_amount_before_publishing_anything` | no partial publication |
| `tests/store/test_write.py::test_both_read_paths_agree_after_an_invalid_batch_is_refused` | the list/frame divergence is unreachable |
| `tests/store/test_write.py::test_read_rejects_an_invalid_row_planted_under_the_store_root` | canonical reconstruction revalidates |
| `tests/store/test_write.py::test_quality_flags_are_an_immutable_tuple` | frozen means frozen |
| `tests/store/test_write.py::test_part_path_rejects_a_run_id_that_is_not_one_safe_segment` | review C2's traversal write |
| `tests/fixtures/test_fixture_dataset.py::test_row_counts` | 162,000 calendar + 27,000 itinerary = 189,000 |
| `tests/fixtures/test_fixture_dataset.py::test_fixture_today_matches_ci_snap_today` | `FIXTURE_TODAY.isoformat()` equals the `SNAP_TODAY` value in `.github/workflows/ci.yml`, and equals the maximum `fetched_date` in the committed parquet |
| `tests/fixtures/test_fixture_dataset.py::test_route_csv_matches_l0_columns` | header and 15 rows exactly as §4.2 |
| `tests/fixtures/test_fixture_dataset.py::test_all_rows_are_one_way_economy_single_pax` | L0 §8 MVP scope |
| `tests/fixtures/test_fixture_dataset.py::test_ap_curve_shape_split` | 40–60% of (route, travel-month) cells are `dip` |
| `tests/fixtures/test_fixture_dataset.py::test_error_fares_are_below_sf05_floor` | all 12 outliers sit below 0.35 × their (route, AP-bucket) median |
| `tests/fixtures/test_fixture_dataset.py::test_ap_bucket_coverage` | every (route, AP bucket) cell has the count in §8 |
| `tests/fixtures/test_fixture_dataset.py::test_no_nullable_column_is_entirely_null_except_the_documented_three` | `return_date`, `stops_return`, `quality_flags` are the only all-null columns |
| `tests/fixtures/test_fixture_dataset.py::test_file_under_10mb` | L0 §7's size budget |
| `tests/fixtures/test_fixture_dataset.py::test_quality_flags_is_null_not_empty_list` | keeps equality tests stable |
| `tests/fixtures/test_fixture_dataset.py::test_validate_fixtures_script_fails_on_a_missing_file` | a missing input exits 1 (review C6) |
| `tests/fixtures/test_fixture_dataset.py::test_validate_fixtures_script_fails_on_a_typo_in_the_fixture_path` | `fare_observation.parquet` (no `s`) exits 1 |
| `tests/fixtures/test_fixture_dataset.py::test_validate_fixtures_script_skips_a_missing_file_only_when_asked` | `--allow-missing` exits 0 |
| `tests/fixtures/test_fixture_dataset.py::test_ci_does_not_pass_allow_missing` | the workflow runs the validator without the escape hatch |

## 8. Observation counts per (route, AP bucket)

Derived from the §4.1 grid; SF-06's confidence rules are checkable against this table
before a line of SF-06 is written.

| AP bucket | dtd values in grid | rows per route (× 90 fetched dates) | reachable confidence |
|---|---|---|---|
| `0-3` | 1–3 | **270** | `medium` at best (≥ 100 so not forced `low`, < 500 so never `high`) |
| `4-7` | 4–7 | **360** | `medium` at best |
| `8-14` | 8–14 | **630** | `high` possible |
| `15-21` | 15–21 | **630** | `high` possible |
| `22-30` | 22–30 | **810** | `high` possible |
| `31-45` | 31–45 | **1350** | `high` possible |
| `46-60` | 46–60 | **1350** | `high` possible |
| `61-90` | 61–90 | **2700** | `high` possible |
| `90+` | 91–120 | **2700** | `high` possible |

Two buckets sit under SF-06's 500-observation `high` threshold and therefore cap at
`medium`. That is variety for SF-07's confidence rendering, not a defect.

**Do not double these counts for tier-1 routes.** The itinerary rows share
`(route, depart_date, fetched_date)` with a calendar row, and SF-06's "prefer `itinerary`
when both exist" rule collapses each pair to one observation. Tier-1 routes have the same
per-cell counts as everyone else; what differs is which source the surviving row came from.

## 9. Interfaces frozen for downstream (SF-06 and SF-07 may assume these)

1. `from pipeline.schema import FareObservation, SCHEMA_VERSION, Source, TripType, Cabin,
   PriceKind, DataQuality, QualityFlag, validate, validate_batch, validated_batch,
   InvalidBatchError, observation_id, build_observation, with_quality` — all importable from
   the package root.
2. `from pipeline.store import SnapshotStore, ReadFilters, default_store`.
3. `SnapshotStore.read_frame(filters) -> pl.DataFrame` with **exactly** the columns, order
   and dtypes in §6, including for an empty result. This is the bulk path; SF-06 must not
   call `read()` for whole-route history.
4. `read()`/`read_frame()` already exclude `data_quality = "rejected"`; SF-06 does not
   re-filter.
5. Rows are already deduplicated on `observation_id` (latest `fetched_at`, then greatest
   `ingest_run_id`). No downstream dedup.
6. Fixture mode is read via `shared.settings.use_fixtures()` / `load_data_settings()` and
   **nowhere else**. A component holding a settings object reports `settings.use_fixtures`
   — `api/`'s `/health` flag is `store.settings.use_fixtures`, not the bare accessor, since
   an injected store may legitimately disagree with the environment (review C4).
   `use_fixtures()` is for code with no settings object to ask.
7. The fixture dataset is 189,000 rows, all `one_way` / `economy` / `passengers = 1` /
   `USD` / `data_quality = "ok"`, over `fetched_date` 2026-06-12 … 2026-09-09 and
   `depart_date` 2026-06-13 … 2027-01-07, with `days_to_departure` 1–120 for every route on
   every fetched date. Per-(route, AP bucket) counts are §8.
8. The 15 route keys are §4.2's list, and `data/fixtures/routes.csv` is the only route file
   that exists in this pass.
9. `SnapshotStore.sources_with_recent_data(within_days, as_of)` exists and backs
   `GET /health`. Its window is `[as_of - within_days, as_of]`, inclusive at both ends
   (review C4): only a lower bound was applied, so a health check as of September 1
   reported a September 9 observation as recent. It runs over the same resolved rows as
   `read()`/`read_frame()`, through the same query builder.
10. `store.write()` never mutates or deletes an existing file, so a test that writes into a
    `tmp_path` store cannot corrupt the fixtures. It validates the whole batch first and
    raises `InvalidBatchError` rather than publishing any part of an invalid batch, so a
    producer must be ready to catch it.
11. "Today" comes from `shared.clock.today_utc()` / `now_utc()` and nowhere else (P0
    §Interfaces frozen 8). `sources_with_recent_data()` already defaults its `as_of` that
    way; SF-06 and SF-07 default theirs the same way rather than calling `date.today()` or
    `datetime.now()`. Under CI's pinned `SNAP_TODAY=2026-09-09` that date is the fixture's
    newest `fetched_date` (`FIXTURE_TODAY`, §4), so "today" is always inside the dataset.

## 10. Out of scope

Everything SF-03 lists, plus: no quality stamping (SF-05), no `config/routes.yaml` (SF-04),
no compaction/retention, no adapters. The store does not pick "the" price for a trip — that
is SF-06's `latest_observed_price()`.

## 11. Ordered commit plan

| # | Message | Contains |
|---|---|---|
| 1 | `Add the canonical fare-observation schema` | `pipeline/schema/enums.py`, `record.py`, `__init__.py`; `tests/schema/test_record.py` |
| 2 | `Pin the observation id canonicalisation` | `pipeline/schema/identity.py`; `tests/schema/test_identity.py` with the 5 fixed vectors |
| 3 | `Add schema validation and the batch report` | `pipeline/schema/validation.py`; `tests/schema/test_validation.py` |
| 4 | `Pin the Arrow schema for the store files` | `pipeline/schema/arrow.py`; `tests/schema/test_arrow.py` |
| 5 | `Read the fixture-mode setting in one place` | `shared/settings.py` |
| 6 | `Write snapshots to the partitioned store` | `pipeline/store/paths.py`, `filters.py`, `snapshot_store.py` (write path); `tests/store/test_write.py` |
| 7 | `Read snapshots back with filters and dedup` | `snapshot_store.py` read/`read_frame`/`sources_with_recent_data`; `tests/store/test_read.py`, `tests/store/test_fixture_mode.py` |
| 8 | `Generate the committed fixture dataset` | `scripts/gen_fixtures.py`, `data/fixtures/routes.csv`, `fare_observations.parquet`, `README.md` |
| 9 | `Validate every fixture row in CI` | `scripts/validate_fixtures.py` body; `tests/fixtures/test_fixture_dataset.py` |

Push after each. Commit 7's test file path is `tests/store/test_fixture_mode.py`. Commits 1–5
are pure-Python and fast to review; 8 is the only one with a large binary in the diff, kept
alone on purpose.

Two ordering consequences, stated so they are not rediscovered as bugs:

- `build_observation()` needs `observation_id()`, so it lands with commit 2 rather than
  commit 1. Commit 1 ships the model and its enums; a commit 1 that imported
  `pipeline.schema.identity` would not run.
- **Commit 8 leaves CI red until commit 9 lands.** It commits
  `data/fixtures/fare_observations.parquet` while `scripts/validate_fixtures.py` is still
  P0's skeleton, and that skeleton raises `NotImplementedError` as soon as the file it
  guards on exists. The CI step P0 wired therefore fails on commit 8 and passes again on
  commit 9. Keeping the binary alone in its own commit is worth one transient red; a future
  spec of this shape should land the validator body *before* the data it validates.
