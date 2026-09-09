"""Partition path construction and discovery for the snapshot store (L0 §6).

```
data/snapshots/fare_observations/
  source={source}/route_key={ORG-DST}/fetched_date={YYYY-MM-DD}/part-{ingest_run_id}.parquet
```
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

PART_PREFIX: str = "part-"
PART_SUFFIX: str = ".parquet"


def partition_dir(root: Path, *, source: str, route_key: str, fetched_date: date) -> Path:
    """{root}/source={source}/route_key={route_key}/fetched_date={YYYY-MM-DD}"""
    return (
        Path(root)
        / f"source={source}"
        / f"route_key={route_key}"
        / f"fetched_date={fetched_date.isoformat()}"
    )


def part_path(
    root: Path,
    *,
    source: str,
    route_key: str,
    fetched_date: date,
    ingest_run_id: str,
    attempt: int = 1,
) -> Path:
    """.../part-{ingest_run_id}.parquet for attempt 1, part-{ingest_run_id}-{attempt:03d}
    .parquet after."""
    if attempt < 1:
        raise ValueError(f"attempt must be >= 1, got {attempt}")
    stem = PART_PREFIX + ingest_run_id
    if attempt > 1:
        stem = f"{stem}-{attempt:03d}"
    directory = partition_dir(root, source=source, route_key=route_key, fetched_date=fetched_date)
    return directory / f"{stem}{PART_SUFFIX}"


def next_free_part_path(
    root: Path, *, source: str, route_key: str, fetched_date: date, ingest_run_id: str
) -> Path:
    """The first part path for this run that does not exist yet. Existing files are never
    rewritten (L0 §6), so a repeated write lands beside the first, not on top of it."""
    attempt = 1
    while True:
        candidate = part_path(
            root,
            source=source,
            route_key=route_key,
            fetched_date=fetched_date,
            ingest_run_id=ingest_run_id,
            attempt=attempt,
        )
        if not candidate.exists():
            return candidate
        attempt += 1


def scan_glob(root: Path) -> str:
    """{root}/source=*/route_key=*/fetched_date=*/part-*.parquet — the DuckDB read_parquet
    argument, with hive_partitioning=1."""
    return str(Path(root) / "source=*" / "route_key=*" / "fetched_date=*" / "part-*.parquet")


def part_files(root: Path) -> list[Path]:
    """Every part file under the store root, sorted. Empty when the root does not exist."""
    directory = Path(root)
    if not directory.exists():
        return []
    return sorted(directory.glob("source=*/route_key=*/fetched_date=*/part-*.parquet"))
