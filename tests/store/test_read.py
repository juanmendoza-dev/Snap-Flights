"""Every filter, cross-file dedup, and the frozen frame contract (L0 §6, SF-03-build §6)."""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from pipeline.schema import DataQuality, PriceKind, Source
from pipeline.schema.arrow import COLUMN_ORDER
from pipeline.store import ReadFilters

from . import RUN_A, RUN_B, make_observation, store_at

FROZEN_FRAME_SCHEMA: dict[str, pl.DataType] = {
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


@pytest.fixture
def populated_store(tmp_path: Path):
    """Four routes, two sources, two fetched dates, two departure dates, one rejected row."""
    store = store_at(tmp_path)
    store.write(
        [
            make_observation(route_key="JFK-LHR", depart_date=date(2026, 12, 20)),
            make_observation(route_key="JFK-LHR", depart_date=date(2027, 1, 5)),
            make_observation(route_key="LHR-JFK", depart_date=date(2026, 12, 20)),
            make_observation(route_key="ORD-DEN", depart_date=date(2026, 12, 20)),
            make_observation(
                route_key="JFK-LHR",
                depart_date=date(2026, 12, 20),
                source=Source.FASTFLIGHTS,
                price_kind=PriceKind.ITINERARY,
                stops_outbound=0,
                carrier_primary="BA",
            ),
            make_observation(
                route_key="JFK-LHR",
                depart_date=date(2026, 12, 20),
                fetched_at=datetime(2026, 9, 8, 6, 0, tzinfo=UTC),
            ),
            make_observation(
                route_key="MAD-LIS",
                depart_date=date(2026, 12, 20),
                data_quality=DataQuality.REJECTED,
            ),
        ]
    )
    return store


def routes(records) -> list[str]:
    return sorted(record.route_key for record in records)


def test_filter_source(populated_store) -> None:
    calendar = populated_store.read(ReadFilters(source=Source.TRAVELPAYOUTS))
    itinerary = populated_store.read(ReadFilters(source=Source.FASTFLIGHTS))

    assert {record.source for record in calendar} == {Source.TRAVELPAYOUTS}
    assert len(itinerary) == 1
    assert itinerary[0].source is Source.FASTFLIGHTS


def test_filter_route_key_single(populated_store) -> None:
    records = populated_store.read(ReadFilters(route_key="LHR-JFK"))

    assert routes(records) == ["LHR-JFK"]


def test_filter_route_key_many(populated_store) -> None:
    records = populated_store.read(ReadFilters(route_key=["LHR-JFK", "ORD-DEN"]))

    assert routes(records) == ["LHR-JFK", "ORD-DEN"]


def test_filter_fetched_date_range(populated_store) -> None:
    older = populated_store.read(
        ReadFilters(fetched_date_from=date(2026, 9, 8), fetched_date_to=date(2026, 9, 8))
    )

    assert len(older) == 1
    assert older[0].fetched_date == date(2026, 9, 8)


def test_filter_fetched_at_range(populated_store) -> None:
    records = populated_store.read(
        ReadFilters(
            fetched_at_from=datetime(2026, 9, 9, 0, 0, tzinfo=UTC),
            fetched_at_to=datetime(2026, 9, 9, 23, 59, tzinfo=UTC),
        )
    )

    assert all(record.fetched_date == date(2026, 9, 9) for record in records)
    assert len(records) == 5  # the six 2026-09-09 rows minus the rejected one


def test_filter_depart_date_range(populated_store) -> None:
    records = populated_store.read(ReadFilters(depart_date_from=date(2027, 1, 1)))

    assert [record.depart_date for record in records] == [date(2027, 1, 5)]


def test_filter_price_kind(populated_store) -> None:
    records = populated_store.read(ReadFilters(price_kind=PriceKind.ITINERARY))

    assert len(records) == 1
    assert records[0].price_kind is PriceKind.ITINERARY


def test_filter_data_quality(populated_store) -> None:
    records = populated_store.read(ReadFilters(data_quality=DataQuality.REJECTED))

    assert routes(records) == ["MAD-LIS"]


def test_rejected_excluded_by_default(populated_store) -> None:
    records = populated_store.read()

    assert "MAD-LIS" not in routes(records)
    assert all(record.data_quality is DataQuality.OK for record in records)


def test_include_rejected_flag(populated_store) -> None:
    records = populated_store.read(ReadFilters(include_rejected=True))

    assert "MAD-LIS" in routes(records)


def test_explicit_data_quality_overrides_include_rejected(populated_store) -> None:
    records = populated_store.read(
        ReadFilters(data_quality=DataQuality.REJECTED, include_rejected=False)
    )

    assert routes(records) == ["MAD-LIS"]


def test_limit(populated_store) -> None:
    records = populated_store.read(ReadFilters(limit=2))

    assert len(records) == 2


def test_cross_file_dedup_keeps_latest_fetched_at(tmp_path: Path) -> None:
    store = store_at(tmp_path)
    store.write([make_observation(amount_minor=42000)])
    store.write(
        [make_observation(amount_minor=39900, fetched_at=datetime(2026, 9, 9, 18, tzinfo=UTC))]
    )

    records = store.read()

    assert len(records) == 1
    assert records[0].amount_minor == 39900
    assert records[0].fetched_at == datetime(2026, 9, 9, 18, tzinfo=UTC)


def test_dedup_tiebreak_on_ingest_run_id(tmp_path: Path) -> None:
    """Same observation_id, identical fetched_at: the greater ingest_run_id wins."""
    store = store_at(tmp_path)
    store.write([make_observation(amount_minor=42000, ingest_run_id=RUN_B)])
    store.write([make_observation(amount_minor=39900, ingest_run_id=RUN_A)])

    records = store.read()

    assert len(records) == 1
    assert records[0].ingest_run_id == RUN_B
    assert records[0].amount_minor == 42000


def test_empty_result_keeps_full_schema(populated_store) -> None:
    frame = populated_store.read_frame(ReadFilters(route_key="SEA-ICN"))

    assert frame.height == 0
    assert frame.columns == list(COLUMN_ORDER)
    assert dict(frame.schema) == FROZEN_FRAME_SCHEMA


def test_empty_store_keeps_full_schema(tmp_path: Path) -> None:
    store = store_at(tmp_path)

    frame = store.read_frame()

    assert store.read() == []
    assert frame.height == 0
    assert dict(frame.schema) == FROZEN_FRAME_SCHEMA


def test_read_frame_schema_is_frozen(populated_store) -> None:
    frame = populated_store.read_frame()

    assert frame.columns == list(COLUMN_ORDER)
    assert dict(frame.schema) == FROZEN_FRAME_SCHEMA
    assert frame.height == 6


def test_read_matches_read_frame(populated_store) -> None:
    for filters in (
        None,
        ReadFilters(route_key="JFK-LHR"),
        ReadFilters(source=Source.FASTFLIGHTS),
        ReadFilters(include_rejected=True),
        ReadFilters(depart_date_from=date(2027, 1, 1)),
    ):
        records = populated_store.read(filters)
        frame = populated_store.read_frame(filters)

        assert [record.observation_id for record in records] == frame["observation_id"].to_list()


def test_sources_with_recent_data(populated_store) -> None:
    recent = populated_store.sources_with_recent_data(as_of=date(2026, 9, 9))
    stale = populated_store.sources_with_recent_data(as_of=date(2026, 10, 1))

    assert recent == {"fastflights": date(2026, 9, 9), "travelpayouts": date(2026, 9, 9)}
    assert stale == {}


def test_sources_with_recent_data_is_empty_without_data(tmp_path: Path) -> None:
    assert store_at(tmp_path).sources_with_recent_data(as_of=date(2026, 9, 9)) == {}


def test_default_store_is_rooted_at_the_repo(repo_root: Path) -> None:
    """SF-03-build §9 freezes default_store() as SF-07's entry point."""
    from pipeline.store import SnapshotStore, default_store

    store = default_store()

    assert isinstance(store, SnapshotStore)
    assert store.settings.repo_root == repo_root
    assert store.snapshots_root == repo_root / "data" / "snapshots" / "fare_observations"
    assert store.settings.fixture_parquet.exists()


def test_default_store_follows_the_fixture_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.store import default_store

    monkeypatch.setenv("SNAP_USE_FIXTURES", "1")
    assert default_store().settings.use_fixtures is True

    monkeypatch.delenv("SNAP_USE_FIXTURES", raising=False)
    assert default_store().settings.use_fixtures is False
