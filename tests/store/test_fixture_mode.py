"""SNAP_USE_FIXTURES: reading the committed dataset with no data/snapshots/ (SF-03 §2).

The fixture Parquet used here is written into ``tmp_path`` rather than read from
``data/fixtures/``: this exercises the union mechanism itself, and keeps the test honest
whichever order the fixture dataset lands in.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from pipeline.schema.arrow import records_to_table
from pipeline.store import ReadFilters
from shared.settings import load_data_settings, use_fixtures

from . import make_observation, store_at


def write_fixture_parquet(root: Path, records) -> Path:
    """Stand in for the committed data/fixtures/fare_observations.parquet."""
    path = root / "data" / "fixtures" / "fare_observations.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(records_to_table(records), path, compression="zstd")
    return path


def test_reads_fixtures_with_no_snapshots_dir(tmp_path: Path) -> None:
    write_fixture_parquet(
        tmp_path,
        [make_observation(route_key="JFK-LHR"), make_observation(route_key="MAD-LIS")],
    )
    store = store_at(tmp_path, use_fixtures=True)

    records = store.read()

    assert not store.snapshots_root.exists()
    assert sorted(record.route_key for record in records) == ["JFK-LHR", "MAD-LIS"]
    assert store.read_frame().height == 2


def test_fixture_mode_off_returns_empty(tmp_path: Path) -> None:
    write_fixture_parquet(tmp_path, [make_observation()])
    store = store_at(tmp_path, use_fixtures=False)

    assert store.read() == []
    assert store.read_frame().height == 0


def test_snapshot_row_supersedes_fixture_row_on_same_id(tmp_path: Path) -> None:
    fixture_row = make_observation(amount_minor=42000)
    write_fixture_parquet(tmp_path, [fixture_row])
    store = store_at(tmp_path, use_fixtures=True)
    store.write(
        [make_observation(amount_minor=31500, fetched_at=datetime(2026, 9, 9, 18, tzinfo=UTC))]
    )

    records = store.read()

    assert len(records) == 1
    assert records[0].observation_id == fixture_row.observation_id
    assert records[0].amount_minor == 31500


def test_fixture_and_snapshot_rows_union_when_ids_differ(tmp_path: Path) -> None:
    write_fixture_parquet(tmp_path, [make_observation(route_key="JFK-LHR")])
    store = store_at(tmp_path, use_fixtures=True)
    store.write([make_observation(route_key="LHR-JFK")])

    assert sorted(record.route_key for record in store.read()) == ["JFK-LHR", "LHR-JFK"]
    assert store.read(ReadFilters(route_key="LHR-JFK"))[0].route_key == "LHR-JFK"


def test_missing_fixture_file_in_fixture_mode_is_not_an_error(tmp_path: Path) -> None:
    store = store_at(tmp_path, use_fixtures=True)

    assert store.read() == []
    assert store.read_frame().height == 0
    assert store.sources_with_recent_data(as_of=date(2026, 9, 9)) == {}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("Yes", True),
        (" yes ", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("", False),
        ("maybe", False),
    ],
)
def test_use_fixtures_env_parsing(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("SNAP_USE_FIXTURES", value)

    assert use_fixtures() is expected
    assert load_data_settings().use_fixtures is expected


def test_explicit_argument_beats_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNAP_USE_FIXTURES", "1")

    assert load_data_settings(use_fixtures=False).use_fixtures is False
    assert load_data_settings().use_fixtures is True


def test_unset_environment_means_fixtures_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAP_USE_FIXTURES", raising=False)

    assert use_fixtures() is False
    assert load_data_settings().use_fixtures is False
