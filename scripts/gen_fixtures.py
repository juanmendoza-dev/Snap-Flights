"""Generate the committed fixture dataset (L0 §7, SF-03-build §4).

Deterministic by construction: **no RNG object anywhere.** Every pseudo-random quantity is a
pure function of a SHA-256 over the seed plus the cell key, so the output does not depend on
iteration order, parallelism, or Python's hash seed.

    uv run python -m scripts.gen_fixtures            # rewrite data/fixtures/
    uv run python -m scripts.gen_fixtures --check    # verify the committed file reproduces
"""

from __future__ import annotations

import argparse
import hashlib
import math
import shutil
import statistics
import sys
import tempfile
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.schema import (
    Cabin,
    PriceKind,
    Source,
    TripType,
    build_observation,
)
from pipeline.schema.arrow import FARE_OBSERVATION_ARROW_SCHEMA, record_to_row

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR: Path = REPO_ROOT / "data" / "fixtures"

SEED: str = "snap-flights-fixtures-v1"
FIXTURE_TODAY: date = date(2026, 9, 9)  # MUST equal CI's SNAP_TODAY (.github/workflows/ci.yml)
FETCHED_DAYS: int = 90
DTD_GRID: range = range(1, 121)
ITINERARY_MAX_DTD: int = 60
FIXTURE_CURRENCY: str = "USD"
FETCH_HOUR_UTC: int = 6

ROUTE_COLUMNS: tuple[str, ...] = ("route_key", "origin", "destination", "region", "tier")

# route_key, region, tier, base price in USD minor units (one-way economy, 1 adult)
ROUTES: tuple[tuple[str, str, int, int], ...] = (
    ("ATL-MIA", "domestic-us", 3, 11000),
    ("BOS-DUB", "transatlantic", 2, 38000),
    ("CDG-FCO", "intra-europe", 3, 8200),
    ("JFK-CDG", "transatlantic", 2, 44000),
    ("JFK-LAX", "domestic-us", 1, 19000),
    ("JFK-LHR", "transatlantic", 1, 42000),
    ("LAX-JFK", "domestic-us", 1, 18500),
    ("LAX-NRT", "transpacific", 1, 62000),
    ("LHR-BCN", "intra-europe", 2, 7500),
    ("LHR-JFK", "transatlantic", 1, 39000),
    ("MAD-LIS", "intra-europe", 3, 6400),
    ("ORD-DEN", "domestic-us", 2, 12500),
    ("SEA-ICN", "transpacific", 3, 55000),
    ("SFO-HND", "transpacific", 2, 58000),
    ("SFO-LHR", "transatlantic", 2, 51000),
)

BASE_MINOR: dict[str, int] = {route: base for route, _, _, base in ROUTES}
TIER: dict[str, int] = {route: tier for route, _, tier, _ in ROUTES}
TIER_1_ROUTES: tuple[str, ...] = tuple(route for route, _, tier, _ in ROUTES if tier == 1)

# Month of travel (index 1..12).
SEASONAL: tuple[float, ...] = (
    0.0,
    0.88,
    0.86,
    0.94,
    1.02,
    1.06,
    1.18,
    1.28,
    1.24,
    1.00,
    0.96,
    0.92,
    1.20,
)

# Weekday of travel, Monday = 0.
DOW: tuple[float, ...] = (1.00, 0.94, 0.95, 1.02, 1.12, 1.06, 1.10)

CARRIERS: dict[str, tuple[str, ...]] = {
    "JFK-LHR": ("BA", "VS", "AA", "DL"),
    "LHR-JFK": ("BA", "VS", "AA", "DL"),
    "LAX-NRT": ("NH", "JL", "UA"),
    "JFK-LAX": ("AA", "DL", "B6", "UA"),
    "LAX-JFK": ("AA", "DL", "B6", "UA"),
}

# (route_key, fetched_date, days_to_departure) — a committed literal, never sampled.
ERROR_FARE_CELLS: tuple[tuple[str, date, int], ...] = (
    ("JFK-LHR", date(2026, 6, 20), 17),
    ("JFK-LHR", date(2026, 8, 2), 73),
    ("LHR-JFK", date(2026, 7, 11), 41),
    ("LAX-NRT", date(2026, 6, 28), 96),
    ("LAX-NRT", date(2026, 8, 19), 12),
    ("SFO-LHR", date(2026, 7, 3), 55),
    ("BOS-DUB", date(2026, 9, 1), 29),
    ("JFK-LAX", date(2026, 6, 15), 6),
    ("JFK-LAX", date(2026, 8, 25), 84),
    ("ORD-DEN", date(2026, 7, 22), 33),
    ("ATL-MIA", date(2026, 6, 30), 108),
    ("MAD-LIS", date(2026, 8, 8), 47),
)

ERROR_FARE_FRACTION: float = 0.22  # of the (route, AP bucket) median; SF-05's floor is 0.35

# Advance-purchase buckets. SF-06 owns the shared definition (models/features/buckets.py);
# the generator carries its own copy because SF-06 does not exist yet.
AP_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0-3", 0, 3),
    ("4-7", 4, 7),
    ("8-14", 8, 14),
    ("15-21", 15, 21),
    ("22-30", 22, 30),
    ("31-45", 31, 45),
    ("46-60", 46, 60),
    ("61-90", 61, 90),
    ("90+", 91, None),
)


def ap_bucket(days_to_departure: int) -> str:
    for name, low, high in AP_BUCKETS:
        if days_to_departure >= low and (high is None or days_to_departure <= high):
            return name
    raise ValueError(f"no AP bucket for days_to_departure={days_to_departure}")


def _h(*parts: object) -> int:
    """int(sha256(SEED + "|" + "|".join(str(p) for p in parts)).hexdigest(), 16)"""
    payload = SEED + "|" + "|".join(str(part) for part in parts)
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest(), 16)


def _unit(*parts: object) -> float:
    """A stable float in [0, 1)."""
    return _h(*parts) % 10**9 / 10**9


def round_to_100(value: float) -> int:
    """Whole currency units: airfares are not quoted in cents (L0 §0)."""
    return math.floor(value / 100.0 + 0.5) * 100


def fetched_dates() -> list[date]:
    """The 90 daily fetch dates ending at FIXTURE_TODAY."""
    return [FIXTURE_TODAY - timedelta(days=offset) for offset in range(FETCHED_DAYS - 1, -1, -1)]


def travel_month(depart_date: date) -> str:
    return f"{depart_date.year:04d}-{depart_date.month:02d}"


def ap_shape(route_key: str, month: str) -> str:
    return "dip" if _h("shape", route_key, month) % 2 == 0 else "rising"


def rising(dtd: int) -> float:
    return 0.98 + 0.62 * math.exp(-dtd / 38.0)


def ap_multiplier(route_key: str, month: str, dtd: int) -> float:
    multiplier = rising(dtd)
    if ap_shape(route_key, month) == "rising":
        return multiplier
    h = _h("dip", route_key, month)
    t0 = 20 + h % 26  # trough centre, 20..45 days out
    depth = 0.10 + (h // 26 % 81) / 1000.0  # 0.100..0.180
    return multiplier * (1.0 - depth * math.exp(-((dtd - t0) ** 2) / (2 * 6.0**2)))


def expected_amount(
    route_key: str, depart_date: date, fetched_date: date, dtd: int, *, premium: float = 1.0
) -> int:
    noise = (_unit("noise", route_key, depart_date, fetched_date) - 0.5) * 0.06
    value = (
        BASE_MINOR[route_key]
        * SEASONAL[depart_date.month]
        * DOW[depart_date.weekday()]
        * ap_multiplier(route_key, travel_month(depart_date), dtd)
        * (1.0 + noise)
        * premium
    )
    return round_to_100(value)


def price_age_seconds(route_key: str, depart_date: date, fetched_date: date) -> int:
    """1h-48h, except a stable 2% subset at 8-14 days so SF-05's stale gate has cases."""
    if _unit("stale", route_key, depart_date, fetched_date) < 0.02:
        span = 1_209_600 - 691_200 + 1
        return 691_200 + _h("age", route_key, depart_date, fetched_date) % span
    return 3600 + _h("age", route_key, depart_date, fetched_date) % (172_800 - 3600 + 1)


def ingest_run_id(fetched_date: date) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://snap.flights/fixtures/{fetched_date}"))


@dataclass(frozen=True, slots=True)
class Outlier:
    route_key: str
    fetched_date: date
    days_to_departure: int
    depart_date: date
    ap_bucket: str
    bucket_median: float
    expected_minor: int
    injected_minor: int

    @property
    def percent_below_expected(self) -> float:
        return 100.0 * (1.0 - self.injected_minor / self.expected_minor)

    @property
    def fraction_of_bucket_median(self) -> float:
        return self.injected_minor / self.bucket_median


@dataclass(frozen=True, slots=True)
class GenerationResult:
    rows: list[dict[str, Any]]
    outliers: list[Outlier]
    dip_cells: int
    total_shape_cells: int

    @property
    def dip_fraction(self) -> float:
        return self.dip_cells / self.total_shape_cells


def _row(
    *,
    source: Source,
    price_kind: PriceKind,
    route_key: str,
    depart_date: date,
    fetched_date: date,
    amount_minor: int,
    stops_outbound: int | None = None,
    carrier_primary: str | None = None,
    observed_price_age_seconds: int | None = None,
    source_native_id_prefix: str | None = None,
) -> dict[str, Any]:
    origin, destination = route_key.split("-")
    fetched_at = datetime(
        fetched_date.year, fetched_date.month, fetched_date.day, FETCH_HOUR_UTC, tzinfo=UTC
    )
    observation = build_observation(
        source=source,
        fetched_at=fetched_at,
        origin=origin,
        destination=destination,
        depart_date=depart_date,
        trip_type=TripType.ONE_WAY,
        cabin=Cabin.ECONOMY,
        passengers=1,
        amount_minor=amount_minor,
        currency=FIXTURE_CURRENCY,
        price_kind=price_kind,
        ingest_run_id=ingest_run_id(fetched_date),
        stops_outbound=stops_outbound,
        carrier_primary=carrier_primary,
        observed_price_age_seconds=observed_price_age_seconds,
    )
    row = record_to_row(observation)
    if source_native_id_prefix is not None:
        # Derived from the id the natural key produced, so it can never drift from it.
        row["source_native_id"] = f"{source_native_id_prefix}{observation.observation_id[:10]}"
    return row


def generate() -> GenerationResult:
    """Every row of the dataset, in insertion order, with the error fares already injected."""
    rows: list[dict[str, Any]] = []
    # (route_key, fetched_date, dtd) -> index into rows, for the error-fare overwrite.
    calendar_index: dict[tuple[str, date, int], int] = {}
    bucket_amounts: dict[tuple[str, str], list[int]] = {}
    shapes: dict[tuple[str, str], str] = {}

    for route_key, _region, tier, _base in ROUTES:
        for fetched_date in fetched_dates():
            for dtd in DTD_GRID:
                depart_date = fetched_date + timedelta(days=dtd)
                month = travel_month(depart_date)
                shapes[(route_key, month)] = ap_shape(route_key, month)

                amount = expected_amount(route_key, depart_date, fetched_date, dtd)
                calendar_index[(route_key, fetched_date, dtd)] = len(rows)
                bucket_amounts.setdefault((route_key, ap_bucket(dtd)), []).append(amount)
                rows.append(
                    _row(
                        source=Source.TRAVELPAYOUTS,
                        price_kind=PriceKind.CALENDAR_CHEAPEST,
                        route_key=route_key,
                        depart_date=depart_date,
                        fetched_date=fetched_date,
                        amount_minor=amount,
                        observed_price_age_seconds=price_age_seconds(
                            route_key, depart_date, fetched_date
                        ),
                    )
                )

                if tier != 1 or dtd > ITINERARY_MAX_DTD:
                    continue

                premium = 1.0 + _unit("prem", route_key, depart_date, fetched_date) * 0.08
                carriers = CARRIERS[route_key]
                rows.append(
                    _row(
                        source=Source.FASTFLIGHTS,
                        price_kind=PriceKind.ITINERARY,
                        route_key=route_key,
                        depart_date=depart_date,
                        fetched_date=fetched_date,
                        amount_minor=expected_amount(
                            route_key, depart_date, fetched_date, dtd, premium=premium
                        ),
                        stops_outbound=(
                            0 if _unit("stops", route_key, depart_date, fetched_date) < 0.55 else 1
                        ),
                        carrier_primary=carriers[
                            _h("carrier", route_key, depart_date, fetched_date) % len(carriers)
                        ],
                        source_native_id_prefix="ff-",
                    )
                )

    outliers = _inject_error_fares(rows, calendar_index, bucket_amounts)

    dip_cells = sum(1 for shape in shapes.values() if shape == "dip")
    return GenerationResult(
        rows=rows,
        outliers=outliers,
        dip_cells=dip_cells,
        total_shape_cells=len(shapes),
    )


def _inject_error_fares(
    rows: list[dict[str, Any]],
    calendar_index: dict[tuple[str, date, int], int],
    bucket_amounts: dict[tuple[str, str], list[int]],
) -> list[Outlier]:
    """Overwrite 12 calendar rows with 0.22 x the (route, AP bucket) median.

    The fraction is defined against the quantity SF-05's floor uses (0.35 x the trailing
    median), so the gate fires by construction — see specs/implementation/README.md
    open question 5. Only the calendar row is overwritten; a tier-1 itinerary row for the
    same cell keeps its normal price.
    """
    outliers: list[Outlier] = []
    for route_key, fetched_date, dtd in ERROR_FARE_CELLS:
        index = calendar_index[(route_key, fetched_date, dtd)]
        row = rows[index]
        bucket = ap_bucket(dtd)
        median = statistics.median(bucket_amounts[(route_key, bucket)])
        injected = round_to_100(ERROR_FARE_FRACTION * median)
        expected = int(row["amount_minor"])
        row["amount_minor"] = injected
        outliers.append(
            Outlier(
                route_key=route_key,
                fetched_date=fetched_date,
                days_to_departure=dtd,
                depart_date=fetched_date + timedelta(days=dtd),
                ap_bucket=bucket,
                bucket_median=median,
                expected_minor=expected,
                injected_minor=injected,
            )
        )

    if len(outliers) != len(ERROR_FARE_CELLS):
        raise RuntimeError(
            f"injected {len(outliers)} error fares, expected {len(ERROR_FARE_CELLS)}"
        )
    return outliers


def sort_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The pinned row order: (route_key, price_kind, fetched_date, depart_date), ascending."""
    return sorted(
        rows,
        key=lambda row: (
            row["route_key"],
            row["price_kind"],
            row["fetched_at"].date(),
            row["depart_date"],
        ),
    )


def build_table(rows: Sequence[dict[str, Any]]) -> pa.Table:
    return pa.Table.from_pylist(list(rows), schema=FARE_OBSERVATION_ARROW_SCHEMA)


def write_parquet(table: pa.Table, path: Path) -> None:
    """Every writer knob explicit: the file has to be byte-reproducible (L0 §7)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        path,
        compression="zstd",
        compression_level=3,
        row_group_size=64_000,
        use_dictionary=[
            "source",
            "origin",
            "destination",
            "route_key",
            "trip_type",
            "cabin",
            "currency",
            "price_kind",
            "data_quality",
            "ingest_run_id",
        ],
        write_statistics=True,
        version="2.6",
        store_schema=True,
        write_page_index=False,
    )


def write_routes_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(ROUTE_COLUMNS)]
    for route_key, region, tier, _base in sorted(ROUTES):
        origin, destination = route_key.split("-")
        lines.append(f"{route_key},{origin},{destination},{region},{tier}")
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_dataset(out_dir: Path, *, result: GenerationResult | None = None) -> tuple[Path, str]:
    """Write routes.csv, fare_observations.parquet and README.md. Returns (parquet, sha256)."""
    generated = result if result is not None else generate()
    parquet_path = out_dir / "fare_observations.parquet"

    write_routes_csv(out_dir / "routes.csv")
    write_parquet(build_table(sort_rows(generated.rows)), parquet_path)
    checksum = sha256_of(parquet_path)
    (out_dir / "README.md").write_text(render_readme(generated, checksum), encoding="utf-8")
    return parquet_path, checksum


def render_readme(result: GenerationResult, checksum: str) -> str:
    """The README is generated, not hand-written, so its numbers cannot drift from the file."""
    dates = fetched_dates()
    calendar_rows = sum(1 for row in result.rows if row["price_kind"] == "calendar_cheapest")
    itinerary_rows = len(result.rows) - calendar_rows
    depart_dates = sorted({row["depart_date"] for row in result.rows})

    base_lines = "\n".join(
        f"| `{route_key}` | {region} | {tier} | {base / 100:,.0f} |"
        for route_key, region, tier, base in ROUTES
    )
    seasonal_line = " | ".join(f"{value:.2f}" for value in SEASONAL[1:])
    dow_line = " | ".join(f"{value:.2f}" for value in DOW)
    outlier_lines = "\n".join(
        f"| `{o.route_key}` | {o.fetched_date} | {o.days_to_departure} | `{o.ap_bucket}` | "
        f"{o.expected_minor / 100:,.0f} | {o.injected_minor / 100:,.0f} | "
        f"{o.percent_below_expected:.1f}% | {o.fraction_of_bucket_median:.3f} |"
        for o in result.outliers
    )
    depths = [o.percent_below_expected for o in result.outliers]

    return f"""# Fixture dataset

**Synthetic. Not real observed prices.** Every number here comes from the price model in
`scripts/gen_fixtures.py`; nothing was collected from a live source. The dataset exists so
the store, the baseline model, the API and the UI can be built and tested before any real
history has been collected (L0 §7).

This file is generated by the generator itself — do not hand-edit it.

## Files

| File | Contents |
|---|---|
| `routes.csv` | the 15 MVP routes: `{", ".join(ROUTE_COLUMNS)}` (columns pinned in L0 §1) |
| `fare_observations.parquet` | {len(result.rows):,} canonical fare observations |
| `README.md` | this file |

## Regenerating

```
uv run python -m scripts.gen_fixtures            # rewrite this directory
uv run python -m scripts.gen_fixtures --check    # verify the committed file reproduces
```

Regeneration is a deliberate, reviewed change (L0 §7): the parquet is committed, so a
regeneration shows up as a binary diff and the SHA-256 below must be updated in the same
commit.

- **Seed:** `{SEED}` — there is no RNG object anywhere in the generator. Every
  pseudo-random quantity is a pure function of `sha256(seed | cell key)`, so the output does
  not depend on iteration order, parallelism or `PYTHONHASHSEED`.
- **Expected SHA-256 of `fare_observations.parquet`:** `{checksum}`
- **Writer:** `pyarrow.parquet.write_table`, zstd level 3, row groups of 64,000, format
  version 2.6, page index off, dictionary encoding on the low-cardinality string columns.
  Byte identity holds for a fixed pyarrow version, which the lockfile pins.
- **Row order (pinned):** `route_key`, `price_kind`, `fetched_date`, `depart_date`, ascending.

## Shape

| | |
|---|---|
| Rows | **{len(result.rows):,}** |
| Rows by kind | {calendar_rows:,} `calendar_cheapest` + {itinerary_rows:,} `itinerary` |
| Routes | {len(ROUTES)} |
| `fetched_date` | {dates[0]} … {dates[-1]} ({len(dates)} daily fetches) |
| `depart_date` | {depart_dates[0]} … {depart_dates[-1]} ({len(depart_dates)} distinct dates) |
| Days to departure | 1-120 for every route on every fetched date |
| "As of" date | {FIXTURE_TODAY} — equals CI's pinned `SNAP_TODAY` |

Every row is `trip_type = one_way`, `return_date = null`, `cabin = economy`,
`passengers = 1`, `currency = {FIXTURE_CURRENCY}`, `data_quality = ok`, `schema_version = 1`
(MVP scope, L0 §8). `data_quality` stays `ok` even on the injected error fares — stamping
quality is SF-05's job, and those rows are what SF-05 has to catch.

`calendar_cheapest` rows come from `travelpayouts` with no itinerary detail;
`itinerary` rows come from `fastflights`, only for the {len(TIER_1_ROUTES)} tier-1 routes
({", ".join(f"`{route}`" for route in TIER_1_ROUTES)}) and only within
{ITINERARY_MAX_DTD} days of departure — the same restriction the real scheduler puts on that
source.

## Price model

```
amount_minor = round_to_100(
      base[route]
    * seasonal[month(depart_date)]
    * dow[weekday(depart_date)]
    * ap_multiplier(route, month(depart_date), days_to_departure)
    * (1 + noise)
    * itinerary_premium
)
```

### Base price per route (USD, one-way economy, 1 adult)

| route | region | tier | base |
|---|---|---|---|
{base_lines}

### Seasonal multiplier, by month of travel

| Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
|---|---|---|---|---|---|---|---|---|---|---|---|
| {seasonal_line} |

### Day-of-week multiplier, by weekday of travel

| Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|
| {dow_line} |

### Advance-purchase curve

`rising(dtd) = 0.98 + 0.62 * exp(-dtd / 38)` — the classic "book early, it climbs" shape:
x1.01 at 120 days out, x1.11 at 60, x1.34 at 21, x1.58 at 1.

Half the `(route, travel month)` cells instead follow a **dip**: the same curve with a
Gaussian trough of 10-18% centred 20-45 days out (sigma = 6 days) before it rises again. The
shape is a parity test on `sha256(seed | route | month)`, so it is stable and roughly even.

Realised split over the {result.total_shape_cells} `(route, travel month)` cells present:
**{result.dip_cells} dip / {result.total_shape_cells - result.dip_cells} rising**
({result.dip_fraction:.1%} dip).

Both shapes are needed so the baseline model's `wait` verdict and the UI's two-verdict
rendering have data to exercise.

### Noise and the itinerary premium

- `noise = (unit(route, depart_date, fetched_date) - 0.5) * 0.06` → ±3% per cell.
- `itinerary_premium = 1 + unit(...) * 0.08` → an itinerary is a specific bookable option, so
  it is never cheaper than the route-level cheapest.

### Provenance columns

- `fetched_at` is `{{fetched_date}}T{FETCH_HOUR_UTC:02d}:00:00Z`; `ingest_run_id` is
  `uuid5(NAMESPACE_URL, "https://snap.flights/fixtures/{{fetched_date}}")` — one run per day.
- `observed_price_age_seconds` is 1h-48h on calendar rows, with a stable 2% subset at
  8-14 days so SF-05's `stale_source_price` gate has cases; it is null on itinerary rows
  (the scraper reads live).
- `source_native_id` is `ff-{{observation_id[:10]}}` on itinerary rows, null on calendar rows.
- `return_date`, `stops_return` and `quality_flags` are null on every row.

## Injected error fares

{len(result.outliers)} calendar rows are overwritten with **{ERROR_FARE_FRACTION} x
median(amount_minor)** for their `(route, AP bucket)`. The fraction is defined against the
quantity SF-05's `price_below_floor` gate uses (floor = 0.35 x the trailing median), so the
gate fires by construction — see open question 5 in `specs/implementation/README.md`. The
realised depth below the cell's *expected* price is recorded here rather than asserted:

| route | fetched_date | dtd | bucket | expected | injected | % below expected | of median |
|---|---|---|---|---|---|---|---|
{outlier_lines}

Realised depth spans {min(depths):.1f}%-{max(depths):.1f}% below expected.

Only the `calendar_cheapest` row of each cell is overwritten; where a tier-1 `itinerary` row
exists for the same cell it keeps its normal price. One source glitching while the other does
not is realistic, and it gives the "prefer itinerary" rule something to hide.
"""


def _describe(result: GenerationResult, parquet_path: Path, checksum: str) -> str:
    size_mb = parquet_path.stat().st_size / 1_000_000
    return (
        f"wrote {len(result.rows):,} rows to {parquet_path} "
        f"({size_mb:.2f} MB)\n"
        f"sha256: {checksum}\n"
        f"dip/rising split: {result.dip_cells}/{result.total_shape_cells - result.dip_cells} "
        f"({result.dip_fraction:.1%} dip)\n"
        f"error fares: {len(result.outliers)}, "
        f"{min(o.percent_below_expected for o in result.outliers):.1f}%-"
        f"{max(o.percent_below_expected for o in result.outliers):.1f}% below expected"
    )


def main(argv: list[str] | None = None) -> int:
    """--out DIR (default data/fixtures) --check (generate to a temp dir and compare
    bytes against the committed file; exit 1 on mismatch, write nothing)."""
    parser = argparse.ArgumentParser(description="Generate the committed fixture dataset.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output directory")
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate into a temp dir and compare bytes with the committed file",
    )
    args = parser.parse_args(argv)

    result = generate()

    if not args.check:
        parquet_path, checksum = write_dataset(args.out, result=result)
        print(_describe(result, parquet_path, checksum))
        return 0

    committed = args.out / "fare_observations.parquet"
    if not committed.exists():
        print(f"check failed: {committed} does not exist")
        return 1

    with tempfile.TemporaryDirectory() as temporary:
        regenerated, checksum = write_dataset(Path(temporary), result=result)
        expected = sha256_of(committed)
        if checksum != expected:
            print(
                "check failed: regenerated file differs from the committed one\n"
                f"  committed:   {expected}\n"
                f"  regenerated: {checksum}"
            )
            _report_value_differences(committed, regenerated)
            return 1
        shutil.copyfile(committed, Path(temporary) / "committed.parquet")

    print(f"check ok: {committed} reproduces byte for byte\nsha256: {expected}")
    return 0


def _report_value_differences(committed: Path, regenerated: Path) -> None:
    """Say whether the *values* differ or only the bytes.

    Byte identity across architectures can break for two very different reasons: the writer
    (zstd build, metadata) or the price model (`math.exp` delegates to platform libm). Only
    the first is a packaging problem; the second is a real data difference. Saying which is
    what makes one CI round-trip enough to diagnose.
    """
    left = pq.read_table(committed, partitioning=None)
    right = pq.read_table(regenerated, partitioning=None)
    if left.schema.equals(right.schema, check_metadata=False) and left.equals(right):
        print("  values are identical — the difference is in the written bytes only")
        return
    print(f"  values differ: committed {left.num_rows:,} rows, regenerated {right.num_rows:,} rows")
    if not left.schema.equals(right.schema, check_metadata=False):
        print("  schemas differ")
        return
    for column in left.column_names:
        if not left.column(column).equals(right.column(column)):
            print(f"  column differs: {column}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
