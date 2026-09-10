"""The Arrow schema is a pinned contract, not an inference (SF-03-build §2.5)."""

from datetime import UTC, date, datetime

import pyarrow as pa
import pytest

from pipeline.schema import (
    COLUMN_ORDER,
    FARE_OBSERVATION_ARROW_SCHEMA,
    Cabin,
    PriceKind,
    QualityFlag,
    Source,
    TripType,
    build_observation,
    records_to_table,
    table_to_records,
)

RUN_ID: str = "11111111-1111-5111-8111-111111111111"

EXPECTED_FIELDS: tuple[tuple[str, pa.DataType, bool], ...] = (
    ("observation_id", pa.string(), False),
    ("source", pa.string(), False),
    ("source_native_id", pa.string(), True),
    ("fetched_at", pa.timestamp("us", tz="UTC"), False),
    ("observed_price_age_seconds", pa.int64(), True),
    ("origin", pa.string(), False),
    ("destination", pa.string(), False),
    ("route_key", pa.string(), False),
    ("depart_date", pa.date32(), False),
    ("return_date", pa.date32(), True),
    ("trip_type", pa.string(), False),
    ("cabin", pa.string(), False),
    ("passengers", pa.int64(), False),
    ("stops_outbound", pa.int64(), True),
    ("stops_return", pa.int64(), True),
    ("carrier_primary", pa.string(), True),
    ("amount_minor", pa.int64(), False),
    ("currency", pa.string(), False),
    ("price_kind", pa.string(), False),
    ("data_quality", pa.string(), False),
    ("quality_flags", pa.list_(pa.string()), True),
    ("ingest_run_id", pa.string(), False),
    ("schema_version", pa.int64(), False),
)


def calendar_row() -> object:
    return build_observation(
        source=Source.TRAVELPAYOUTS,
        fetched_at=datetime(2026, 9, 9, 6, 0, tzinfo=UTC),
        origin="JFK",
        destination="LHR",
        depart_date=date(2026, 12, 20),
        trip_type=TripType.ONE_WAY,
        cabin=Cabin.ECONOMY,
        passengers=1,
        amount_minor=42000,
        currency="USD",
        price_kind=PriceKind.CALENDAR_CHEAPEST,
        ingest_run_id=RUN_ID,
        observed_price_age_seconds=3600,
    )


def itinerary_row() -> object:
    return build_observation(
        source=Source.FASTFLIGHTS,
        fetched_at=datetime(2026, 9, 9, 6, 0, tzinfo=UTC),
        origin="LAX",
        destination="NRT",
        depart_date=date(2026, 10, 1),
        trip_type=TripType.ONE_WAY,
        cabin=Cabin.ECONOMY,
        passengers=1,
        amount_minor=62000,
        currency="USD",
        price_kind=PriceKind.ITINERARY,
        ingest_run_id=RUN_ID,
        stops_outbound=1,
        carrier_primary="NH",
        source_native_id="ff-0123456789",
        quality_flags=[QualityFlag.PRICE_BELOW_FLOOR],
    )


def test_arrow_schema_is_pinned() -> None:
    assert len(FARE_OBSERVATION_ARROW_SCHEMA) == len(EXPECTED_FIELDS)

    for index, (name, arrow_type, nullable) in enumerate(EXPECTED_FIELDS):
        field = FARE_OBSERVATION_ARROW_SCHEMA.field(index)
        assert field.name == name
        assert field.type == arrow_type
        assert field.nullable is nullable

    assert tuple(name for name, _, _ in EXPECTED_FIELDS) == COLUMN_ORDER


def test_records_table_roundtrip() -> None:
    records = [calendar_row(), itinerary_row()]

    table = records_to_table(records)

    assert table.schema.equals(FARE_OBSERVATION_ARROW_SCHEMA, check_metadata=False)
    assert table.column_names == list(COLUMN_ORDER)
    assert table.schema.field("fetched_at").type == pa.timestamp("us", tz="UTC")
    assert table_to_records(table) == records


def test_enums_are_written_as_plain_strings() -> None:
    table = records_to_table([itinerary_row()])

    for column in ("source", "trip_type", "cabin", "price_kind", "data_quality"):
        assert table.schema.field(column).type == pa.string()

    assert table.column("source").to_pylist() == ["fastflights"]
    assert table.column("price_kind").to_pylist() == ["itinerary"]
    assert table.column("quality_flags").to_pylist() == [["price_below_floor"]]


def test_all_null_nullable_columns_keep_their_declared_type() -> None:
    table = records_to_table([calendar_row()])

    assert table.column("return_date").to_pylist() == [None]
    assert table.schema.field("return_date").type == pa.date32()
    assert table.schema.field("stops_return").type == pa.int64()
    assert table.schema.field("quality_flags").type == pa.list_(pa.string())


def test_empty_batch_keeps_the_full_schema() -> None:
    table = records_to_table([])

    assert table.num_rows == 0
    assert table.schema.equals(FARE_OBSERVATION_ARROW_SCHEMA, check_metadata=False)


def test_table_to_records_rejects_a_mismatched_schema() -> None:
    table = records_to_table([calendar_row()])
    dropped = table.drop_columns(["currency"])

    with pytest.raises(ValueError, match="does not match FARE_OBSERVATION_ARROW_SCHEMA"):
        table_to_records(dropped)


def test_table_to_records_rejects_a_drifted_timestamp_unit() -> None:
    table = records_to_table([calendar_row()])
    drifted = table.set_column(
        table.column_names.index("fetched_at"),
        pa.field("fetched_at", pa.timestamp("ns", tz="UTC"), nullable=False),
        table.column("fetched_at").cast(pa.timestamp("ns", tz="UTC")),
    )

    with pytest.raises(ValueError, match="does not match FARE_OBSERVATION_ARROW_SCHEMA"):
        table_to_records(drifted)
