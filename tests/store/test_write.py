"""The write path: partitioning, batch dedup, and never touching an existing file (L0 §6).

``pq.read_table(..., partitioning=None)`` throughout: the part files keep ``source``,
``route_key`` and ``fetched_date`` as real columns as well as Hive path segments (SF-03-build
§2.5), so letting pyarrow re-derive them from the path collides with the file's own columns.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow.parquet as pq

from pipeline.schema import PriceKind, Source
from pipeline.schema.arrow import FARE_OBSERVATION_ARROW_SCHEMA
from pipeline.store.paths import part_files, part_path

from . import RUN_A, RUN_B, make_observation, store_at


def test_write_lays_out_the_l0_partition_path(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    record = make_observation()

    result = store.write([record])

    expected = part_path(
        store.snapshots_root,
        source="travelpayouts",
        route_key="JFK-LHR",
        fetched_date=date(2026, 9, 9),
        ingest_run_id=RUN_A,
    )
    assert result.paths == [expected]
    assert expected.exists()
    assert expected.parent == (
        store.snapshots_root
        / "source=travelpayouts"
        / "route_key=JFK-LHR"
        / "fetched_date=2026-09-09"
    )


def test_write_splits_one_file_per_source_route_and_fetched_date(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    records = [
        make_observation(route_key="JFK-LHR"),
        make_observation(route_key="LHR-JFK"),
        make_observation(
            route_key="JFK-LHR",
            source=Source.FASTFLIGHTS,
            price_kind=PriceKind.ITINERARY,
            stops_outbound=0,
            carrier_primary="BA",
        ),
        make_observation(route_key="JFK-LHR", fetched_at=datetime(2026, 9, 8, 6, 0, tzinfo=UTC)),
    ]

    result = store.write(records)

    assert result.files_written == 4
    assert result.records_written == 4
    assert result.duplicates_dropped == 0
    assert len(part_files(store.snapshots_root)) == 4


def test_batch_dedup_keeps_last_occurrence(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    first = make_observation(amount_minor=42000)
    last = make_observation(amount_minor=39900)
    assert first.observation_id == last.observation_id  # amount is not in the natural key

    result = store.write([first, last])

    assert result.records_written == 1
    assert result.duplicates_dropped == 1
    table = pq.read_table(result.paths[0], partitioning=None)
    assert table.column("amount_minor").to_pylist() == [39900]


def test_second_write_creates_a_second_part_file(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    records = [make_observation()]

    first = store.write(records)
    second = store.write(records)

    assert first.paths != second.paths
    assert second.paths[0].name.endswith("-002.parquet")
    assert len(part_files(store.snapshots_root)) == 2


def test_write_never_mutates_an_existing_file(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    original = store.write([make_observation(amount_minor=42000)])
    before = original.paths[0].read_bytes()

    store.write([make_observation(amount_minor=10000)])

    assert original.paths[0].read_bytes() == before


def test_different_runs_write_different_files(tmp_path: Path) -> None:
    store = store_at(tmp_path)

    store.write([make_observation(ingest_run_id=RUN_A)])
    store.write([make_observation(ingest_run_id=RUN_B)])

    names = sorted(path.name for path in part_files(store.snapshots_root))
    assert names == [f"part-{RUN_A}.parquet", f"part-{RUN_B}.parquet"]


def test_part_files_carry_the_pinned_schema_and_partition_columns(tmp_path: Path) -> None:
    store = store_at(tmp_path)

    result = store.write([make_observation()])

    table = pq.read_table(result.paths[0], partitioning=None)
    assert table.schema.equals(FARE_OBSERVATION_ARROW_SCHEMA, check_metadata=False)
    assert table.column("source").to_pylist() == ["travelpayouts"]
    assert table.column("route_key").to_pylist() == ["JFK-LHR"]


def test_empty_batch_is_a_no_op(tmp_path: Path) -> None:
    store = store_at(tmp_path)

    result = store.write([])

    assert (result.files_written, result.records_written, result.duplicates_dropped) == (0, 0, 0)
    assert result.paths == []
    assert not store.snapshots_root.exists()
