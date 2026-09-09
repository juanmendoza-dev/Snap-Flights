"""The append-only snapshot store (L0 §6).

Writes go to one Parquet part file per ``(source, route_key, fetched_date, ingest_run)``
under ``data/snapshots/fare_observations/``. Files are never rewritten or deleted; a
repeated write lands beside the first and read-time dedup resolves the overlap.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import pyarrow.parquet as pq

from pipeline.schema.arrow import records_to_table
from pipeline.schema.record import FareObservation
from pipeline.store.paths import next_free_part_path
from shared.settings import DataSettings, default_data_settings, load_data_settings

PART_COMPRESSION: str = "zstd"
PART_COMPRESSION_LEVEL: int = 3
PART_FORMAT_VERSION: str = "2.6"


@dataclass(frozen=True, slots=True)
class WriteResult:
    files_written: int
    records_written: int
    duplicates_dropped: int
    paths: list[Path] = field(default_factory=list)


class SnapshotStore:
    """Read and write the append-only fare-observation history."""

    def __init__(self, settings: DataSettings | None = None) -> None:
        """settings defaults to load_data_settings()."""
        self.settings = settings if settings is not None else load_data_settings()

    @property
    def snapshots_root(self) -> Path:
        return self.settings.snapshots_root

    def write(self, records: Sequence[FareObservation]) -> WriteResult:
        """Group by (source, route_key, fetched_date); dedup within the batch on
        observation_id keeping the LAST occurrence; write one
        part-{ingest_run_id}.parquet per group under the L0 §6 layout. Never rewrites
        or deletes an existing file: if the target path exists, a numeric suffix is
        appended (part-{run}-002.parquet). Empty batch is a no-op returning zeros."""
        if not records:
            return WriteResult(files_written=0, records_written=0, duplicates_dropped=0, paths=[])

        deduped: dict[str, FareObservation] = {}
        for record in records:
            deduped[record.observation_id] = record
        duplicates_dropped = len(records) - len(deduped)

        groups: dict[tuple[str, str, str, str], list[FareObservation]] = {}
        for record in deduped.values():
            key = (
                str(record.source),
                record.route_key,
                record.fetched_date.isoformat(),
                record.ingest_run_id,
            )
            groups.setdefault(key, []).append(record)

        paths: list[Path] = []
        written = 0
        for (source, route_key, _fetched_date, ingest_run_id), group in sorted(groups.items()):
            target = next_free_part_path(
                self.snapshots_root,
                source=source,
                route_key=route_key,
                fetched_date=group[0].fetched_date,
                ingest_run_id=ingest_run_id,
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(
                records_to_table(group),
                target,
                compression=PART_COMPRESSION,
                compression_level=PART_COMPRESSION_LEVEL,
                version=PART_FORMAT_VERSION,
                write_statistics=True,
            )
            paths.append(target)
            written += len(group)

        return WriteResult(
            files_written=len(paths),
            records_written=written,
            duplicates_dropped=duplicates_dropped,
            paths=paths,
        )


@cache
def _store_for(settings: DataSettings) -> SnapshotStore:
    return SnapshotStore(settings)


def default_store() -> SnapshotStore:
    """Process-wide store built from load_data_settings(). Cached."""
    return _store_for(default_data_settings())
