"""Partition path construction and discovery for the snapshot store (L0 §6).

```
data/snapshots/fare_observations/
  source={source}/route_key={ORG-DST}/fetched_date={YYYY-MM-DD}/part-{ingest_run_id}.parquet
```
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

PART_PREFIX: str = "part-"
PART_SUFFIX: str = ".parquet"

# A partition value is one path segment and nothing else. The model already bounds what can
# reach here (IATA codes, an enum, a UUID), but the store owns its own filesystem boundary:
# a value that travels between processes or arrives from a hand-built call must not be able
# to name a directory of its own.
_SAFE_COMPONENT: re.Pattern[str] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _checked_component(name: str, value: str) -> str:
    """One path segment, or ValueError. Rejects separators, dot segments and NUL."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"unsafe_path_component: {name} must be a non-empty string, got {value!r}")
    if value in {".", ".."} or not _SAFE_COMPONENT.match(value):
        raise ValueError(
            f"unsafe_path_component: {name} {value!r} is not a single safe path segment"
        )
    return value


def under_root(root: Path, target: Path) -> Path:
    """`target`, asserted to resolve inside `root`. Both sides are resolved first: the store
    root itself may be a symlink (a temp dir on macOS routinely is)."""
    resolved_root = Path(root).resolve()
    resolved_target = Path(target).resolve()
    if not resolved_target.is_relative_to(resolved_root):
        raise ValueError(
            f"escaped_store_root: {resolved_target} is not under the store root {resolved_root}"
        )
    return target


def partition_dir(root: Path, *, source: str, route_key: str, fetched_date: date) -> Path:
    """{root}/source={source}/route_key={route_key}/fetched_date={YYYY-MM-DD}"""
    directory = (
        Path(root)
        / f"source={_checked_component('source', source)}"
        / f"route_key={_checked_component('route_key', route_key)}"
        / f"fetched_date={_checked_component('fetched_date', fetched_date.isoformat())}"
    )
    return under_root(root, directory)


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
    stem = PART_PREFIX + _checked_component("ingest_run_id", ingest_run_id)
    if attempt > 1:
        stem = f"{stem}-{attempt:03d}"
    directory = partition_dir(root, source=source, route_key=route_key, fetched_date=fetched_date)
    return under_root(root, directory / f"{stem}{PART_SUFFIX}")


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
    argument, with hive_partitioning=0.

    Inference is off because `source` and `route_key` are real columns in the file as well as
    path segments (SF-03-build §2.5): re-deriving them from the path yields dictionary-typed
    columns that collide with the file's own string columns. `fetched_date` is a path segment
    only, and a query that filters on it computes CAST(fetched_at AS DATE) under a UTC
    session timezone instead.
    """
    return str(Path(root) / "source=*" / "route_key=*" / "fetched_date=*" / "part-*.parquet")


def part_files(root: Path) -> list[Path]:
    """Every part file under the store root, sorted. Empty when the root does not exist."""
    directory = Path(root)
    if not directory.exists():
        return []
    return sorted(directory.glob("source=*/route_key=*/fetched_date=*/part-*.parquet"))
