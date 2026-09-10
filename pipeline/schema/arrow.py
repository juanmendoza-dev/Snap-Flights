"""The pinned physical (Arrow/Parquet) schema for fare observations (SF-03-build §2.5).

Every nullable column is written with an explicit type so Arrow cannot infer ``null`` for a
column that happens to be all-null in one batch (``return_date``, ``stops_return`` and
``quality_flags`` are all-null across this whole pass), and so the timestamp unit never
drifts as data crosses DuckDB, polars and pyarrow.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pyarrow as pa

from pipeline.schema.record import FareObservation
from pipeline.schema.validation import validated_batch

FARE_OBSERVATION_ARROW_SCHEMA: pa.Schema = pa.schema(
    [
        pa.field("observation_id", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("source_native_id", pa.string(), nullable=True),
        pa.field("fetched_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("observed_price_age_seconds", pa.int64(), nullable=True),
        pa.field("origin", pa.string(), nullable=False),
        pa.field("destination", pa.string(), nullable=False),
        pa.field("route_key", pa.string(), nullable=False),
        pa.field("depart_date", pa.date32(), nullable=False),
        pa.field("return_date", pa.date32(), nullable=True),
        pa.field("trip_type", pa.string(), nullable=False),
        pa.field("cabin", pa.string(), nullable=False),
        pa.field("passengers", pa.int64(), nullable=False),
        pa.field("stops_outbound", pa.int64(), nullable=True),
        pa.field("stops_return", pa.int64(), nullable=True),
        pa.field("carrier_primary", pa.string(), nullable=True),
        pa.field("amount_minor", pa.int64(), nullable=False),
        pa.field("currency", pa.string(), nullable=False),
        pa.field("price_kind", pa.string(), nullable=False),
        pa.field("data_quality", pa.string(), nullable=False),
        pa.field("quality_flags", pa.list_(pa.string()), nullable=True),
        pa.field("ingest_run_id", pa.string(), nullable=False),
        pa.field("schema_version", pa.int64(), nullable=False),
    ]
)

COLUMN_ORDER: tuple[str, ...] = tuple(FARE_OBSERVATION_ARROW_SCHEMA.names)

_ENUM_COLUMNS: tuple[str, ...] = ("source", "trip_type", "cabin", "price_kind", "data_quality")


def record_to_row(record: FareObservation) -> dict[str, Any]:
    """One record as a plain dict in COLUMN_ORDER, enums flattened to their string values."""
    row = record.model_dump()
    for column in _ENUM_COLUMNS:
        row[column] = str(row[column])
    flags = row["quality_flags"]
    row["quality_flags"] = None if flags is None else [str(flag) for flag in flags]
    return {column: row[column] for column in COLUMN_ORDER}


def records_to_table(records: Sequence[FareObservation]) -> pa.Table:
    """Column order is COLUMN_ORDER, types are FARE_OBSERVATION_ARROW_SCHEMA. Enums are
    written as their string values, never as Arrow dictionaries."""
    rows = [record_to_row(record) for record in records]
    return pa.Table.from_pylist(rows, schema=FARE_OBSERVATION_ARROW_SCHEMA)


def table_to_records(table: pa.Table) -> list[FareObservation]:
    """Inverse. Raises on a schema mismatch rather than coercing, and revalidates every row
    — including the logical id and schema version (review C1). Matching the physical schema
    says the bytes are shaped right; it says nothing about whether the id recomputes from
    the natural key it claims. Raises InvalidBatchError with the full report if not."""
    if not table.schema.equals(FARE_OBSERVATION_ARROW_SCHEMA, check_metadata=False):
        raise ValueError(
            "table schema does not match FARE_OBSERVATION_ARROW_SCHEMA:\n"
            f"expected:\n{FARE_OBSERVATION_ARROW_SCHEMA}\ngot:\n{table.schema}"
        )
    return validated_batch(table.to_pylist())
