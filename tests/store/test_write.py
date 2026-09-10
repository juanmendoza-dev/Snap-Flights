"""The write path: partitioning, batch dedup, and never touching an existing file (L0 §6).

``pq.read_table(..., partitioning=None)`` throughout: the part files keep ``source``,
``route_key`` and ``fetched_date`` as real columns as well as Hive path segments (SF-03-build
§2.5), so letting pyarrow re-derive them from the path collides with the file's own columns.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from pipeline.schema import (
    DataQuality,
    FareObservation,
    PriceKind,
    QualityFlag,
    Source,
    ViolationCode,
    with_quality,
)
from pipeline.schema.arrow import FARE_OBSERVATION_ARROW_SCHEMA
from pipeline.store import InvalidBatchError
from pipeline.store.paths import part_files, part_path, under_root

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


def test_rewrite_same_batch_is_idempotent_on_read(tmp_path: Path) -> None:
    """Physical duplicate part files are fine; read-time dedup collapses them (L0 §6)."""
    store = store_at(tmp_path)
    records = [make_observation(route_key="JFK-LHR"), make_observation(route_key="LHR-JFK")]

    store.write(records)
    store.write(records)
    store.write(records)

    assert len(part_files(store.snapshots_root)) == 6
    read_back = store.read()
    assert len(read_back) == 2
    assert sorted(record.observation_id for record in read_back) == sorted(
        record.observation_id for record in records
    )


# C2 — a partition value is one path segment, and the target stays under the store root.


@pytest.mark.parametrize(
    "run_id",
    [
        "x/../../../../../escaped",
        "../escaped",
        "..",
        ".",
        "",
        "a/b",
        "a\\b",
        "a\x00b",
    ],
)
def test_part_path_rejects_a_run_id_that_is_not_one_safe_segment(
    tmp_path: Path, run_id: str
) -> None:
    """`x/../../../../../escaped` used to write data/snapshots/escaped.parquet, outside the
    fare store's scan tree entirely."""
    with pytest.raises(ValueError, match="unsafe_path_component"):
        part_path(
            tmp_path,
            source="travelpayouts",
            route_key="JFK-LHR",
            fetched_date=date(2026, 9, 9),
            ingest_run_id=run_id,
        )


@pytest.mark.parametrize("component", ["source", "route_key"])
def test_part_path_rejects_a_traversing_partition_value(tmp_path: Path, component: str) -> None:
    kwargs: dict[str, object] = {
        "source": "travelpayouts",
        "route_key": "JFK-LHR",
        "fetched_date": date(2026, 9, 9),
        "ingest_run_id": RUN_A,
    }
    kwargs[component] = "../../escaped"

    with pytest.raises(ValueError, match="unsafe_path_component"):
        part_path(tmp_path, **kwargs)  # type: ignore[arg-type]


def test_under_root_rejects_a_target_outside_the_store(tmp_path: Path) -> None:
    root = tmp_path / "fare_observations"

    assert under_root(root, root / "source=travelpayouts") == root / "source=travelpayouts"
    with pytest.raises(ValueError, match="escaped_store_root"):
        under_root(root, tmp_path / "escaped.parquet")


def test_writing_a_traversing_run_id_is_impossible_end_to_end(tmp_path: Path) -> None:
    """The model refuses the run id before the store ever sees it, and nothing lands
    anywhere near the store root."""
    store_at(tmp_path)

    with pytest.raises(ValidationError):
        make_observation(ingest_run_id="x/../../../../../escaped")

    assert list(tmp_path.rglob("*.parquet")) == []


# C1 — write is the trust boundary: a FareObservation instance proves nothing.


def invalid_copy(**update: object) -> FareObservation:
    """A valid record copied with an invalid field. model_copy runs no validators, so this
    is a FareObservation instance that never met one."""
    return make_observation().model_copy(update=update)


def test_write_rejects_a_negative_price_carried_in_by_model_copy(tmp_path: Path) -> None:
    """The C1 reproduction: validate() used to report nothing, the writer persisted -1,
    read_frame() returned -1 and read() raised."""
    store = store_at(tmp_path)

    with pytest.raises(InvalidBatchError) as caught:
        store.write([invalid_copy(amount_minor=-1)])

    report = caught.value.report
    assert report.invalid == 1
    assert ViolationCode.NONPOSITIVE_AMOUNT in report.counts_by_code
    assert part_files(store.snapshots_root) == []


def test_write_rejects_a_record_whose_id_does_not_recompute(tmp_path: Path) -> None:
    store = store_at(tmp_path)

    with pytest.raises(InvalidBatchError) as caught:
        store.write([invalid_copy(observation_id="0" * 16)])

    assert ViolationCode.OBSERVATION_ID_MISMATCH in caught.value.report.counts_by_code
    assert part_files(store.snapshots_root) == []


def test_write_rejects_a_wrong_schema_version(tmp_path: Path) -> None:
    store = store_at(tmp_path)

    with pytest.raises(InvalidBatchError) as caught:
        store.write([invalid_copy(schema_version=2)])

    assert ViolationCode.BAD_SCHEMA_VERSION in caught.value.report.counts_by_code


def test_write_rejects_an_overflowing_amount_before_publishing_anything(tmp_path: Path) -> None:
    """2**63 used to pass validation and raise OverflowError inside pyarrow — after the
    earlier partition groups of the same batch had already been written."""
    store = store_at(tmp_path)
    batch = [
        make_observation(route_key="JFK-LHR"),
        make_observation(route_key="LHR-JFK"),
        invalid_copy(amount_minor=2**63),
    ]

    with pytest.raises(InvalidBatchError):
        store.write(batch)

    assert part_files(store.snapshots_root) == []
    assert store.read() == []


def test_the_report_covers_the_whole_batch_not_just_the_first_bad_row(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    batch = [
        make_observation(),
        invalid_copy(amount_minor=-1),
        invalid_copy(observation_id="0" * 16),
    ]

    with pytest.raises(InvalidBatchError) as caught:
        store.write(batch)

    report = caught.value.report
    assert (report.total, report.valid, report.invalid) == (3, 1, 2)


def test_both_read_paths_agree_after_an_invalid_batch_is_refused(tmp_path: Path) -> None:
    """The list/frame divergence the review reproduced is unreachable once the write gate
    is mandatory: neither path ever sees the row."""
    store = store_at(tmp_path)
    good = make_observation()
    store.write([good])

    with pytest.raises(InvalidBatchError):
        store.write([invalid_copy(amount_minor=-1)])

    records = store.read()
    frame = store.read_frame()
    assert [record.observation_id for record in records] == frame["observation_id"].to_list()
    assert [record.amount_minor for record in records] == frame["amount_minor"].to_list()
    assert records == [good]


def test_read_rejects_an_invalid_row_planted_under_the_store_root(tmp_path: Path) -> None:
    """Nothing can write this through the store, so plant it directly: canonical
    reconstruction revalidates and refuses it, with the full report."""
    store = store_at(tmp_path)
    store.write([make_observation()])
    planted = part_files(store.snapshots_root)[0]
    table = pq.read_table(planted, schema=FARE_OBSERVATION_ARROW_SCHEMA)
    corrupted = table.set_column(
        table.column_names.index("observation_id"),
        table.schema.field("observation_id"),
        pa.array(["0" * 16] * table.num_rows, type=pa.string()),
    )
    pq.write_table(corrupted, planted.with_name("part-planted.parquet"))

    with pytest.raises(InvalidBatchError) as caught:
        store.read()

    assert ViolationCode.OBSERVATION_ID_MISMATCH in caught.value.report.counts_by_code
    # read_frame() is the bulk path and trusts the write gate, so it still returns the row.
    assert store.read_frame().height == 2


def test_quality_flags_are_an_immutable_tuple() -> None:
    """A frozen model with a mutable list is not frozen. SF-05 stamps flags on these."""
    record = with_quality(
        make_observation(),
        data_quality=DataQuality.SUSPECT,
        quality_flags=[QualityFlag.PRICE_BELOW_FLOOR],
    )

    assert record.quality_flags == (QualityFlag.PRICE_BELOW_FLOOR,)
    with pytest.raises(AttributeError):
        record.quality_flags.append(QualityFlag.STALE_SOURCE_PRICE)  # type: ignore[union-attr]


def test_with_quality_revalidates_and_write_accepts_the_result(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    stamped = with_quality(
        make_observation(),
        data_quality=DataQuality.SUSPECT,
        quality_flags=[QualityFlag.PRICE_BELOW_FLOOR],
    )

    store.write([stamped])

    assert store.read() == [stamped]
    with pytest.raises(ValidationError):
        with_quality(
            make_observation().model_copy(update={"amount_minor": -1}),
            data_quality=DataQuality.REJECTED,
        )
