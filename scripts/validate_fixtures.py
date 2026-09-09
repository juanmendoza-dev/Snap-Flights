"""Validate the committed fixture dataset against the canonical schema.

Asserts the Parquet file's physical schema equals the pinned Arrow schema field-for-field,
runs the batch validator over every row, checks `routes.csv`'s columns against L0 §1, and
prints the report. Exits 1 on any violation; exits 0 with a skip notice when the fixture
file does not exist yet.

    uv run python scripts/validate_fixtures.py
"""

import argparse
import csv
import sys
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parent.parent

# CI runs this as a plain script (`uv run python scripts/validate_fixtures.py`), which puts
# scripts/ on sys.path rather than the repo root. Imports are rooted at the repo root
# (P0 §Interfaces frozen 1), so put it there before importing anything from pipeline/.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.schema import validate_batch  # noqa: E402
from pipeline.schema.arrow import FARE_OBSERVATION_ARROW_SCHEMA  # noqa: E402

FIXTURE_PATH = REPO_ROOT / "data" / "fixtures" / "fare_observations.parquet"
ROUTES_PATH = REPO_ROOT / "data" / "fixtures" / "routes.csv"

ROUTE_COLUMNS: tuple[str, ...] = ("route_key", "origin", "destination", "region", "tier")
BATCH_ROWS: int = 20_000


def schema_differences(path: Path) -> list[str]:
    """Field-for-field comparison against the pinned schema: name, type, nullability."""
    actual = pq.read_schema(path)
    expected = FARE_OBSERVATION_ARROW_SCHEMA
    differences: list[str] = []

    if actual.names != expected.names:
        differences.append(f"column order/name mismatch: {actual.names} != {expected.names}")
        return differences

    for field in expected:
        found = actual.field(field.name)
        if found.type != field.type:
            differences.append(f"{field.name}: type {found.type} != {field.type}")
        if found.nullable != field.nullable:
            differences.append(f"{field.name}: nullable {found.nullable} != {field.nullable}")
    return differences


def routes_differences(path: Path) -> list[str]:
    """routes.csv carries exactly the columns L0 §1 pins, in order."""
    if not path.exists():
        return [f"{path} does not exist"]

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        rows = list(reader)

    differences: list[str] = []
    if tuple(header) != ROUTE_COLUMNS:
        differences.append(f"routes.csv columns {tuple(header)} != {ROUTE_COLUMNS}")
    for index, row in enumerate(rows):
        if len(row) != len(ROUTE_COLUMNS):
            differences.append(f"routes.csv row {index}: {len(row)} fields, expected 5")
            continue
        route_key, origin, destination, _region, tier = row
        if route_key != f"{origin}-{destination}":
            differences.append(
                f"routes.csv row {index}: route_key {route_key} != {origin}-{destination}"
            )
        if tier not in {"1", "2", "3"}:
            differences.append(f"routes.csv row {index}: tier {tier!r} is not 1, 2 or 3")
    return differences


def validate_rows(path: Path) -> int:
    """Run the batch validator over every row and print the report. Returns the exit code."""
    parquet = pq.ParquetFile(path)
    rows = (
        row for batch in parquet.iter_batches(batch_size=BATCH_ROWS) for row in batch.to_pylist()
    )
    report = validate_batch(rows)
    print(report)
    return 1 if report.invalid else 0


def main(argv: list[str] | None = None) -> int:
    """Validate every row of data/fixtures/fare_observations.parquet against the
    canonical schema. Returns 0 on success, 1 on any violation, 0 with a printed
    skip notice when the fixture file does not exist yet (P0 state)."""
    parser = argparse.ArgumentParser(description="Validate the committed fixture dataset.")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=FIXTURE_PATH,
        help="Parquet file to validate (default: data/fixtures/fare_observations.parquet)",
    )
    args = parser.parse_args(argv)
    path: Path = args.path

    if not path.exists():
        try:
            shown = path.relative_to(REPO_ROOT)
        except ValueError:
            shown = path
        print(f"skip: {shown} does not exist yet — nothing to validate")
        return 0

    exit_code = 0

    differences = schema_differences(path)
    if differences:
        print(f"schema mismatch in {path}:")
        for difference in differences:
            print(f"  {difference}")
        exit_code = 1
    else:
        print(f"schema ok: {path} matches FARE_OBSERVATION_ARROW_SCHEMA")

    route_problems = routes_differences(ROUTES_PATH)
    if route_problems:
        print(f"routes.csv problems in {ROUTES_PATH}:")
        for problem in route_problems:
            print(f"  {problem}")
        exit_code = 1
    else:
        print(f"routes ok: {ROUTES_PATH.name} matches the L0 §1 columns")

    return max(exit_code, validate_rows(path))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
