"""The committed fixture dataset: shape, determinism, size and schema validity (L0 §7)."""

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest
import yaml

from pipeline.schema import validate_batch
from scripts import gen_fixtures, validate_fixtures
from scripts.gen_fixtures import (
    ERROR_FARE_CELLS,
    ERROR_FARE_FRACTION,
    FIXTURE_TODAY,
    ROUTE_COLUMNS,
    ROUTES,
    ap_bucket,
    ap_shape,
    travel_month,
)

SF05_FLOOR_FRACTION: float = 0.35  # SF-05's price_below_floor: 0.35 x the trailing median

# SF-03-build §8: rows per route per AP bucket, over the calendar_cheapest stream.
EXPECTED_BUCKET_COUNTS: dict[str, int] = {
    "0-3": 270,
    "4-7": 360,
    "8-14": 630,
    "15-21": 630,
    "22-30": 810,
    "31-45": 1350,
    "46-60": 1350,
    "61-90": 2700,
    "90+": 2700,
}

EXPECTED_ROUTES_CSV: str = """route_key,origin,destination,region,tier
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
"""


@pytest.fixture(scope="session")
def fixture_parquet(repo_root: Path) -> Path:
    return repo_root / "data" / "fixtures" / "fare_observations.parquet"


@pytest.fixture(scope="session")
def frame(fixture_parquet: Path) -> pl.DataFrame:
    """The committed dataset with fetched_date and days_to_departure derived."""
    return (
        pl.read_parquet(fixture_parquet)
        .with_columns(fetched_date=pl.col("fetched_at").dt.date())
        .with_columns(
            days_to_departure=(pl.col("depart_date") - pl.col("fetched_date")).dt.total_days()
        )
    )


@pytest.fixture(scope="session")
def calendar_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """The calendar_cheapest stream — the one SF-03-build §8's counts describe."""
    return frame.filter(pl.col("price_kind") == "calendar_cheapest").with_columns(
        ap_bucket=pl.col("days_to_departure").map_elements(ap_bucket, return_dtype=pl.String)
    )


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_row_counts(frame: pl.DataFrame) -> None:
    counts = dict(frame.group_by("price_kind").len().iter_rows())

    assert counts == {"calendar_cheapest": 162_000, "itinerary": 27_000}
    assert frame.height == 189_000


def test_every_fixture_row_validates(fixture_parquet: Path) -> None:
    parquet = pq.ParquetFile(fixture_parquet)
    rows = (row for batch in parquet.iter_batches(batch_size=20_000) for row in batch.to_pylist())

    report = validate_batch(rows)

    assert report.total == 189_000
    assert report.invalid == 0, str(report)
    assert report.ok


def test_all_rows_are_one_way_economy_single_pax(frame: pl.DataFrame) -> None:
    assert frame["trip_type"].unique().to_list() == ["one_way"]
    assert frame["cabin"].unique().to_list() == ["economy"]
    assert frame["passengers"].unique().to_list() == [1]
    assert frame["currency"].unique().to_list() == ["USD"]
    assert frame["data_quality"].unique().to_list() == ["ok"]
    assert frame["schema_version"].unique().to_list() == [1]
    assert frame["return_date"].null_count() == frame.height


def test_grid_covers_every_route_on_every_fetched_date(frame: pl.DataFrame) -> None:
    assert frame["fetched_date"].n_unique() == 90
    assert str(frame["fetched_date"].min()) == "2026-06-12"
    assert str(frame["fetched_date"].max()) == "2026-09-09"
    assert str(frame["depart_date"].min()) == "2026-06-13"
    assert str(frame["depart_date"].max()) == "2027-01-07"
    assert frame["depart_date"].n_unique() == 209
    assert frame["days_to_departure"].min() == 1
    assert frame["days_to_departure"].max() == 120


def test_fixture_today_matches_ci_snap_today(repo_root: Path, frame: pl.DataFrame) -> None:
    workflow = yaml.safe_load((repo_root / ".github" / "workflows" / "ci.yml").read_text())

    snap_today = workflow["jobs"]["check"]["env"]["SNAP_TODAY"]

    assert snap_today == FIXTURE_TODAY.isoformat()
    assert str(frame["fetched_date"].max()) == snap_today


def test_route_csv_matches_l0_columns(repo_root: Path) -> None:
    text = (repo_root / "data" / "fixtures" / "routes.csv").read_text(encoding="utf-8")

    assert text == EXPECTED_ROUTES_CSV
    assert text.splitlines()[0].split(",") == list(ROUTE_COLUMNS)
    assert len(text.splitlines()) == 1 + len(ROUTES) == 16


def test_itinerary_rows_are_tier_one_and_inside_the_window(frame: pl.DataFrame) -> None:
    itinerary = frame.filter(pl.col("price_kind") == "itinerary")

    assert sorted(itinerary["route_key"].unique().to_list()) == [
        "JFK-LAX",
        "JFK-LHR",
        "LAX-JFK",
        "LAX-NRT",
        "LHR-JFK",
    ]
    assert itinerary["days_to_departure"].max() == 60
    assert itinerary["source"].unique().to_list() == ["fastflights"]
    assert itinerary["stops_outbound"].null_count() == 0
    assert itinerary["carrier_primary"].null_count() == 0
    assert itinerary["source_native_id"].null_count() == 0


def test_ap_bucket_coverage(calendar_frame: pl.DataFrame) -> None:
    """Per (route, AP bucket) counts, over the calendar stream only (SF-03-build §8)."""
    counts = calendar_frame.group_by(["route_key", "ap_bucket"]).len()

    assert counts.height == len(ROUTES) * len(EXPECTED_BUCKET_COUNTS)
    for route_key, bucket, count in counts.iter_rows():
        assert count == EXPECTED_BUCKET_COUNTS[bucket], f"{route_key}/{bucket}"


def test_ap_curve_shape_split(frame: pl.DataFrame) -> None:
    cells = {
        (route_key, travel_month(depart_date))
        for route_key, depart_date in frame.select(["route_key", "depart_date"]).iter_rows()
    }

    dip = sum(1 for route_key, month in cells if ap_shape(route_key, month) == "dip")

    assert len(cells) == 120  # 15 routes x 8 travel months
    assert 0.40 <= dip / len(cells) <= 0.60


def test_error_fares_are_below_sf05_floor(calendar_frame: pl.DataFrame) -> None:
    medians = calendar_frame.group_by(["route_key", "ap_bucket"]).agg(
        pl.col("amount_minor").median().alias("bucket_median")
    )
    cells = pl.DataFrame(
        {
            "route_key": [cell[0] for cell in ERROR_FARE_CELLS],
            "fetched_date": [cell[1] for cell in ERROR_FARE_CELLS],
            "days_to_departure": [cell[2] for cell in ERROR_FARE_CELLS],
        },
        schema_overrides={"days_to_departure": pl.Int64},
    )

    injected = (
        cells.with_columns(
            ap_bucket=pl.col("days_to_departure").map_elements(ap_bucket, return_dtype=pl.String)
        )
        .join(
            calendar_frame.select(
                ["route_key", "fetched_date", "days_to_departure", "amount_minor"]
            ),
            on=["route_key", "fetched_date", "days_to_departure"],
        )
        .join(medians, on=["route_key", "ap_bucket"])
    )

    assert injected.height == len(ERROR_FARE_CELLS) == 12
    for row in injected.iter_rows(named=True):
        ratio = row["amount_minor"] / row["bucket_median"]
        assert ratio < SF05_FLOOR_FRACTION, row
        assert ratio == pytest.approx(ERROR_FARE_FRACTION, abs=0.01), row


def test_no_nullable_column_is_entirely_null_except_the_documented_three(
    frame: pl.DataFrame,
) -> None:
    all_null = {
        column
        for column in frame.columns
        if column not in {"fetched_date", "days_to_departure"}
        and frame[column].null_count() == frame.height
    }

    assert all_null == {"return_date", "stops_return", "quality_flags"}


def test_quality_flags_is_null_not_empty_list(frame: pl.DataFrame) -> None:
    assert frame["quality_flags"].null_count() == frame.height
    assert frame.filter(pl.col("quality_flags").list.len() == 0).height == 0


def test_file_under_10mb(fixture_parquet: Path) -> None:
    assert fixture_parquet.stat().st_size < 10 * 1000 * 1000


def test_sha256_matches_readme(repo_root: Path, fixture_parquet: Path) -> None:
    readme = (repo_root / "data" / "fixtures" / "README.md").read_text(encoding="utf-8")

    documented = re.search(r"\b([0-9a-f]{64})\b", readme)

    assert documented is not None, "README.md records no SHA-256"
    assert documented.group(1) == sha256_of(fixture_parquet)


@pytest.mark.slow
def test_regeneration_is_byte_identical(tmp_path: Path, fixture_parquet: Path) -> None:
    """Regenerate from scratch and compare.

    Values are compared before bytes on purpose: if the values match and only the bytes
    differ, the cause is the writer (zstd build, embedded metadata); if the values differ,
    the cause is the price model itself (``math.exp`` delegates to platform libm). The two
    need different fixes, so the failure has to say which one it is.
    """
    regenerated, checksum = gen_fixtures.write_dataset(tmp_path)

    committed_table = pq.read_table(fixture_parquet, partitioning=None)
    regenerated_table = pq.read_table(regenerated, partitioning=None)
    assert regenerated_table.schema.equals(committed_table.schema, check_metadata=False)
    assert regenerated_table.equals(committed_table), "row values differ, not just the bytes"

    assert checksum == sha256_of(fixture_parquet)
    assert regenerated.read_bytes() == fixture_parquet.read_bytes()


@pytest.mark.slow
def test_generator_check_mode_confirms_the_committed_file(repo_root: Path) -> None:
    assert gen_fixtures.main(["--check"]) == 0


def test_validate_fixtures_script_exits_zero(repo_root: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/validate_fixtures.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "189000 rows: 189000 valid, 0 invalid" in completed.stdout


def test_validate_fixtures_script_exits_one_on_a_corrupted_copy(
    tmp_path: Path, fixture_parquet: Path
) -> None:
    table = pq.read_table(fixture_parquet, partitioning=None).slice(0, 500)
    corrupted = table.set_column(
        table.column_names.index("amount_minor"),
        table.schema.field("amount_minor"),
        pl.Series("amount_minor", [0] * table.num_rows, dtype=pl.Int64).to_arrow(),
    )
    path = tmp_path / "corrupted.parquet"
    pq.write_table(corrupted, path)

    assert validate_fixtures.main([str(path)]) == 1


def test_validate_fixtures_script_skips_a_missing_file(tmp_path: Path) -> None:
    assert validate_fixtures.main([str(tmp_path / "absent.parquet")]) == 0
