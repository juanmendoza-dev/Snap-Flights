"""The append-only snapshot store (L0 §6).

Writes go to one Parquet part file per ``(source, route_key, fetched_date, ingest_run)``
under ``data/snapshots/fare_observations/``. Files are never rewritten or deleted; a
repeated write lands beside the first and read-time dedup resolves the overlap: the row with
the latest ``fetched_at`` wins, ties broken by the greater ``ingest_run_id``.

``write()`` is the store's trust boundary: it revalidates every record from its own field
values before anything is grouped, deduped or published. ``read()`` revalidates again on
canonical reconstruction; ``read_frame()`` trusts the write gate, because revalidating a
whole training scan row by row would defeat the point of the bulk path.

``read()`` and ``read_frame()`` share one query builder so the spec-literal path and the bulk
path can never diverge. ``read_frame()`` returns the frozen schema of SF-03-build §6 — the
same columns, order and dtypes for an empty result as for a full one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cache
from pathlib import Path

import duckdb
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.schema.arrow import COLUMN_ORDER, FARE_OBSERVATION_ARROW_SCHEMA, records_to_table
from pipeline.schema.arrow import table_to_records as arrow_table_to_records
from pipeline.schema.record import FareObservation
from pipeline.schema.validation import validated_batch
from pipeline.store.filters import ReadFilters, as_list
from pipeline.store.paths import next_free_part_path, part_files, scan_glob
from shared.clock import today_utc
from shared.settings import DataSettings, default_data_settings, load_data_settings

# The frozen read_frame() schema (SF-03-build §6). Enum columns are plain strings, never
# categoricals: a categorical carries a per-frame string cache that makes cross-frame joins
# unreliable.
FRAME_SCHEMA: dict[str, pl.DataType] = {
    "observation_id": pl.String(),
    "source": pl.String(),
    "source_native_id": pl.String(),
    "fetched_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    "observed_price_age_seconds": pl.Int64(),
    "origin": pl.String(),
    "destination": pl.String(),
    "route_key": pl.String(),
    "depart_date": pl.Date(),
    "return_date": pl.Date(),
    "trip_type": pl.String(),
    "cabin": pl.String(),
    "passengers": pl.Int64(),
    "stops_outbound": pl.Int64(),
    "stops_return": pl.Int64(),
    "carrier_primary": pl.String(),
    "amount_minor": pl.Int64(),
    "currency": pl.String(),
    "price_kind": pl.String(),
    "data_quality": pl.String(),
    "quality_flags": pl.List(pl.String()),
    "ingest_run_id": pl.String(),
    "schema_version": pl.Int64(),
}

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
        """Validate the whole batch, then group by (source, route_key, fetched_date);
        dedup within the batch on observation_id keeping the LAST occurrence; write one
        part-{ingest_run_id}.parquet per group under the L0 §6 layout. Never rewrites
        or deletes an existing file: if the target path exists, a numeric suffix is
        appended (part-{run}-002.parquet). Empty batch is a no-op returning zeros.

        Validation is mandatory and comes first (review C1/C2). Every record is rebuilt
        from its own field values — being a FareObservation instance proves nothing, since
        model_copy(update=...) and model_construct() both skip the validators — and an
        invalid batch raises InvalidBatchError carrying the full report, before dedup has
        chosen a winner or a single file has been published. Arrow conversion of every
        group happens before the first write for the same reason: a value that overflows
        int64 used to fail mid-publication, with earlier partitions already on disk."""
        if not records:
            return WriteResult(files_written=0, records_written=0, duplicates_dropped=0, paths=[])

        validated = validated_batch(records)

        deduped: dict[str, FareObservation] = {}
        for record in validated:
            deduped[record.observation_id] = record
        duplicates_dropped = len(validated) - len(deduped)

        groups: dict[tuple[str, str, str, str], list[FareObservation]] = {}
        for record in deduped.values():
            key = (
                str(record.source),
                record.route_key,
                record.fetched_date.isoformat(),
                record.ingest_run_id,
            )
            groups.setdefault(key, []).append(record)

        # Both loops run to completion before the first file is written: path construction
        # and Arrow conversion are where a bad value still shows up, and a half-published
        # batch is not something an append-only store can take back.
        planned: list[tuple[Path, pa.Table, int]] = []
        for (source, route_key, _fetched_date, ingest_run_id), group in sorted(groups.items()):
            target = next_free_part_path(
                self.snapshots_root,
                source=source,
                route_key=route_key,
                fetched_date=group[0].fetched_date,
                ingest_run_id=ingest_run_id,
            )
            planned.append((target, records_to_table(group), len(group)))

        paths: list[Path] = []
        written = 0
        for target, table, count in planned:
            target.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(
                table,
                target,
                compression=PART_COMPRESSION,
                compression_level=PART_COMPRESSION_LEVEL,
                version=PART_FORMAT_VERSION,
                write_statistics=True,
            )
            paths.append(target)
            written += count

        return WriteResult(
            files_written=len(paths),
            records_written=written,
            duplicates_dropped=duplicates_dropped,
            paths=paths,
        )

    def _scan_targets(self) -> list[str]:
        """The Parquet paths and globs to scan, fixtures first (SF-03-build §2.8)."""
        targets: list[str] = []
        if self.settings.use_fixtures and self.settings.fixture_parquet.exists():
            targets.append(str(self.settings.fixture_parquet))
        if part_files(self.snapshots_root):
            targets.append(scan_glob(self.snapshots_root))
        return targets

    def _build_query(self, filters: ReadFilters) -> tuple[str, list[object]]:
        """The single query both read paths use. Filters run before the dedup window so
        Parquet predicate pushdown can skip whole row groups."""
        conditions: list[str] = []
        params: list[object] = []

        for column, values in (
            ("source", as_list(filters.source)),
            ("route_key", as_list(filters.route_key)),
            ("price_kind", as_list(filters.price_kind)),
            ("data_quality", as_list(filters.data_quality)),
        ):
            if values is None:
                continue
            placeholders = ", ".join("?" for _ in values)
            conditions.append(f"{column} IN ({placeholders})")
            params.extend(values)

        if filters.data_quality is None and not filters.include_rejected:
            conditions.append("data_quality <> ?")
            params.append("rejected")

        # fetched_date is the UTC calendar date of fetched_at (L0 §6); it is a path segment
        # and a derived value, never a stored column, so it is recomputed here.
        for condition, value in (
            ("CAST(fetched_at AS DATE) >= ?", filters.fetched_date_from),
            ("CAST(fetched_at AS DATE) <= ?", filters.fetched_date_to),
            ("fetched_at >= ?", filters.fetched_at_from),
            ("fetched_at <= ?", filters.fetched_at_to),
            ("depart_date >= ?", filters.depart_date_from),
            ("depart_date <= ?", filters.depart_date_to),
        ):
            if value is None:
                continue
            conditions.append(condition)
            params.append(value)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        columns = ", ".join(COLUMN_ORDER)
        limit = ""
        if filters.limit is not None:
            limit = "LIMIT ?"

        query = f"""
            WITH scanned AS (
                SELECT {columns}
                FROM read_parquet(?, hive_partitioning = 0, union_by_name = true)
                {where}
            ), ranked AS (
                SELECT *, row_number() OVER (
                    PARTITION BY observation_id
                    ORDER BY fetched_at DESC, ingest_run_id DESC
                ) AS rn
                FROM scanned
            )
            SELECT * EXCLUDE (rn)
            FROM ranked
            WHERE rn = 1
            ORDER BY fetched_at, observation_id
            {limit}
        """
        if filters.limit is not None:
            params.append(filters.limit)
        return query, params

    def _connect(self) -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect()
        # CAST(timestamptz AS DATE) is session-timezone dependent; fetched_date is UTC.
        connection.execute("SET TimeZone = 'UTC'")
        return connection

    def read(self, filters: ReadFilters | None = None) -> list[FareObservation]:
        """Spec-literal path: canonical records. Convenience for tests and small reads.
        Do not call this for whole-route history — use read_frame().

        Reconstruction revalidates every row, id and schema version included (review C1);
        read_frame() does not, and is not meant to — it is the bulk path, and write() is
        the gate that keeps invalid rows out of the store in the first place. The two
        agree on every row that came in through write()."""
        table = self.read_frame(filters).to_arrow().cast(FARE_OBSERVATION_ARROW_SCHEMA)
        return arrow_table_to_records(table)

    def read_frame(self, filters: ReadFilters | None = None) -> pl.DataFrame:
        """Bulk path. Same rows, same filtering, same dedup as read(), returned as a
        polars DataFrame with the frozen schema in SF-03-build §6."""
        resolved = filters if filters is not None else ReadFilters()
        # An empty selection is answered here, not by DuckDB: `IN ()` is a parser error, and
        # the answer must not depend on whether the store happens to hold data yet (C3).
        targets = self._scan_targets()
        if not targets or resolved.selects_nothing:
            return _empty_frame()

        query, params = self._build_query(resolved)
        connection = self._connect()
        try:
            frame = connection.execute(query, [targets, *params]).pl()
        finally:
            connection.close()
        return _conform(frame)

    def sources_with_recent_data(
        self, *, within_days: int = 3, as_of: date | None = None
    ) -> dict[str, date]:
        """source -> most recent fetched_date, for sources seen within the window.
        `as_of` defaults to shared.clock.today_utc() — never date.today(), so a pinned
        SNAP_TODAY makes /health deterministic against the fixture calendar."""
        targets = self._scan_targets()
        if not targets:
            return {}

        cutoff = (as_of if as_of is not None else today_utc()) - timedelta(days=within_days)
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT source, max(CAST(fetched_at AS DATE)) AS last_fetched_date
                FROM read_parquet(?, hive_partitioning = 0, union_by_name = true)
                WHERE data_quality <> 'rejected'
                GROUP BY source
                HAVING max(CAST(fetched_at AS DATE)) >= ?
                ORDER BY source
                """,
                [targets, cutoff],
            ).fetchall()
        finally:
            connection.close()
        return {str(source): last_fetched for source, last_fetched in rows}


def _empty_frame() -> pl.DataFrame:
    """An empty frame carrying the full frozen schema, never a zero-column frame."""
    return pl.DataFrame(schema=FRAME_SCHEMA)


def _conform(frame: pl.DataFrame) -> pl.DataFrame:
    """Select in COLUMN_ORDER and cast to the frozen dtypes, so the contract holds by
    construction rather than by trusting DuckDB's inference."""
    return frame.select([pl.col(name).cast(dtype) for name, dtype in FRAME_SCHEMA.items()])


@cache
def _store_for(settings: DataSettings) -> SnapshotStore:
    return SnapshotStore(settings)


def default_store() -> SnapshotStore:
    """Process-wide store built from load_data_settings(). Cached."""
    return _store_for(default_data_settings())
